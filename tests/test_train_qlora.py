"""Offline unit and batch-masking tests for QLoRA fine-tuning setup."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import torch
from tokenizers import Tokenizer, decoders, models, pre_tokenizers
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    PreTrainedTokenizerFast,
    Qwen2Config,
    Qwen2ForCausalLM,
)
from trl import SFTTrainer

from training.prepare_dataset import format_example, write_jsonl
from training.train_qlora import (
    build_bnb_config,
    build_lora_config,
    build_sft_config,
    cast_bfloat16_for_fp16,
    is_native_bf16_supported,
    load_config,
    load_prompt_completion_splits,
    main,
    resolve_precision,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
QWEN_CHAT_TEMPLATE = (
    "{%- for message in messages -%}"
    "{{- '<|im_start|>' + message['role'] + '\\n' + message['content'] + '<|im_end|>\\n' -}}"
    "{%- endfor -%}"
    "{%- if add_generation_prompt -%}"
    "{{- '<|im_start|>assistant\\n' -}}"
    "{%- endif -%}"
)


def _create_tiny_qwen_model(model_dir: Path) -> Path:
    """Save a tiny offline Qwen2 model + ByteLevel ChatML tokenizer for CPU tests."""
    byte_syms = pre_tokenizers.ByteLevel.alphabet()
    vocab = {sym: idx for idx, sym in enumerate(byte_syms)}
    tok_obj = Tokenizer(models.BPE(vocab=vocab, merges=[]))
    tok_obj.pre_tokenizer = pre_tokenizers.ByteLevel(add_prefix_space=False)
    tok_obj.decoder = decoders.ByteLevel()
    fast_tok = PreTrainedTokenizerFast(
        tokenizer_object=tok_obj,
        eos_token="<|im_end|>",
        pad_token="<|endoftext|>",
        additional_special_tokens=["<|im_start|>", "<|im_end|>", "<|endoftext|>"],
        chat_template=QWEN_CHAT_TEMPLATE,
    )
    model_dir.mkdir(parents=True, exist_ok=True)
    fast_tok.save_pretrained(str(model_dir))
    cfg = Qwen2Config(
        vocab_size=len(fast_tok),
        hidden_size=32,
        intermediate_size=64,
        num_hidden_layers=1,
        num_attention_heads=2,
        num_key_value_heads=2,
        bos_token_id=fast_tok.pad_token_id,
        eos_token_id=fast_tok.eos_token_id,
        pad_token_id=fast_tok.pad_token_id,
    )
    Qwen2ForCausalLM(cfg).save_pretrained(str(model_dir))
    return model_dir


def _write_tiny_splits(data_dir: Path) -> tuple[Path, Path]:
    train_rows = [
        format_example(
            "school_db",
            "CREATE TABLE students (id INTEGER PRIMARY KEY, name TEXT, gpa REAL);",
            f"List students with GPA >= {g}.",
            f"SELECT name FROM students WHERE gpa >= {g}",
        )
        for g in (3.0, 3.2, 3.5, 3.8)
    ]
    val_rows = [
        format_example(
            "store_db",
            "CREATE TABLE orders (id INTEGER PRIMARY KEY, amount REAL);",
            "Count all orders.",
            "SELECT COUNT(*) FROM orders",
        )
    ]
    train_path, val_path = data_dir / "train.jsonl", data_dir / "val.jsonl"
    write_jsonl(train_rows, train_path)
    write_jsonl(val_rows, val_path)
    return train_path, val_path


def test_config_loading_and_t4_float16_fallback() -> None:
    cfg = load_config(REPO_ROOT / "training" / "config.yaml")
    assert cfg["model"]["base_model_id"] == "Qwen/Qwen2.5-3B-Instruct"

    ampere = resolve_precision(cfg, use_cuda=True, bf16_supported=True, dry_run=False)
    assert (ampere.compute_dtype, ampere.use_bf16, ampere.use_fp16, ampere.use_quantization) == (
        torch.bfloat16, True, False, True
    )

    t4 = resolve_precision(cfg, use_cuda=True, bf16_supported=False, dry_run=False)
    assert (t4.compute_dtype, t4.use_bf16, t4.use_fp16, t4.use_quantization) == (
        torch.float16, False, True, True
    )

    cpu_dry = resolve_precision(cfg, use_cuda=False, bf16_supported=False, dry_run=True)
    assert (cpu_dry.compute_dtype, cpu_dry.use_quantization) == (torch.float32, False)

    with pytest.raises(RuntimeError, match="CUDA GPU"):
        resolve_precision(cfg, use_cuda=False, bf16_supported=False, dry_run=False)


def test_native_bf16_ignores_emulation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: True)
    monkeypatch.setattr(
        torch.cuda,
        "is_bf16_supported",
        lambda including_emulation=True: including_emulation,
    )
    assert is_native_bf16_supported() is False


def test_cast_bfloat16_for_fp16_handles_trainable_and_frozen(tmp_path: Path) -> None:
    cfg = load_config(REPO_ROOT / "training" / "config.yaml")
    model_dir = _create_tiny_qwen_model(tmp_path / "bf16_qwen")
    bf16_model = AutoModelForCausalLM.from_pretrained(str(model_dir), dtype=torch.bfloat16)
    bf16_model.save_pretrained(str(model_dir))

    t4_precision = resolve_precision(cfg, use_cuda=True, bf16_supported=False, dry_run=False)
    assert t4_precision.compute_dtype == torch.float16
    loaded = AutoModelForCausalLM.from_pretrained(str(model_dir), dtype=t4_precision.compute_dtype)
    assert all(p.dtype == torch.float16 for p in loaded.parameters())

    train_path, val_path = _write_tiny_splits(tmp_path / "data")
    train_ds, val_ds = load_prompt_completion_splits(train_path, val_path)
    tok = AutoTokenizer.from_pretrained(str(model_dir))
    cpu_cfg = resolve_precision(cfg, use_cuda=False, bf16_supported=False, dry_run=True)
    sft_cfg = build_sft_config(cfg["training"], cpu_cfg, tmp_path / "out", smoketest=False, dry_run=True)
    trainer = SFTTrainer(
        model=loaded,
        args=sft_cfg,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        peft_config=build_lora_config(cfg["lora"]),
        processing_class=tok,
    )
    frozen_param = next(p for p in trainer.model.parameters() if not p.requires_grad)
    trainable_param = next(p for p in trainer.model.parameters() if p.requires_grad)
    frozen_param.data = frozen_param.data.to(torch.bfloat16)
    trainable_param.data = trainable_param.data.to(torch.bfloat16)

    cast_bfloat16_for_fp16(trainer.model)
    assert all(p.dtype != torch.bfloat16 for p in trainer.model.parameters())
    assert frozen_param.dtype == torch.float16
    assert trainable_param.dtype == torch.float32


def test_bnb_and_lora_configs_match_yaml() -> None:
    cfg = load_config(REPO_ROOT / "training" / "config.yaml")
    bnb = build_bnb_config(cfg["quantization"], torch.float16)
    assert bnb.load_in_4bit is True
    assert bnb.bnb_4bit_quant_type == "nf4"
    assert bnb.bnb_4bit_use_double_quant is True
    assert bnb.bnb_4bit_compute_dtype == torch.float16

    lora = build_lora_config(cfg["lora"])
    assert lora.r == 16
    assert lora.lora_alpha == 32
    assert lora.lora_dropout == pytest.approx(0.05)
    assert set(lora.target_modules) == {"q_proj", "k_proj", "v_proj", "o_proj", "gate_proj", "up_proj", "down_proj"}


def test_completion_only_loss_masks_prompt_and_keeps_sql_labels(tmp_path: Path) -> None:
    cfg = load_config(REPO_ROOT / "training" / "config.yaml")
    model_dir = _create_tiny_qwen_model(tmp_path / "tiny_qwen")
    train_path, val_path = _write_tiny_splits(tmp_path / "data")
    train_ds, val_ds = load_prompt_completion_splits(train_path, val_path)

    tokenizer = AutoTokenizer.from_pretrained(str(model_dir))
    model = AutoModelForCausalLM.from_pretrained(str(model_dir))
    precision = resolve_precision(cfg, use_cuda=False, bf16_supported=False, dry_run=True)
    sft_cfg = build_sft_config(cfg["training"], precision, tmp_path / "out", smoketest=False, dry_run=True)
    assert sft_cfg.completion_only_loss is True

    trainer = SFTTrainer(
        model=model,
        args=sft_cfg,
        train_dataset=train_ds,
        eval_dataset=val_ds,
        peft_config=build_lora_config(cfg["lora"]),
        processing_class=tokenizer,
    )
    batch: dict[str, Any] = next(iter(trainer.get_train_dataloader()))
    input_ids, labels = batch["input_ids"][0], batch["labels"][0]
    assert (labels == -100).any(), "Prompt tokens must be masked with -100."
    assert (labels != -100).any(), "Completion SQL tokens must not be masked."

    unmasked_ids = input_ids[labels != -100].tolist()
    masked_ids = input_ids[(labels == -100) & (input_ids != tokenizer.pad_token_id)].tolist()
    decoded_completion = tokenizer.decode(unmasked_ids, skip_special_tokens=True)
    decoded_prompt = tokenizer.decode(masked_ids, skip_special_tokens=True)
    assert "SELECT name FROM students" in decoded_completion
    assert "CREATE TABLE students" not in decoded_completion
    assert "CREATE TABLE students" in decoded_prompt


def test_dry_run_cli_end_to_end(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(torch.cuda, "is_available", lambda: False)
    model_dir = _create_tiny_qwen_model(tmp_path / "tiny_qwen")
    train_path, val_path = _write_tiny_splits(tmp_path / "data")
    out_dir = tmp_path / "dry_out"

    rc = main([
        "--config", str(REPO_ROOT / "training" / "config.yaml"),
        "--dry-run",
        "--model-override", str(model_dir),
        "--train-file", str(train_path),
        "--val-file", str(val_path),
        "--output-dir", str(out_dir),
    ])
    assert rc == 0
    summary = json.loads((out_dir / "training_summary.json").read_text(encoding="utf-8"))
    assert summary["mode"] == "dry-run"
    assert summary["completion_only_loss"] is True
    assert summary["batch_verification"]["masked_tokens"] > 0
    assert summary["batch_verification"]["unmasked_tokens"] > 0


def test_train_qlora_line_budget() -> None:
    lines = (REPO_ROOT / "training" / "train_qlora.py").read_text(encoding="utf-8").splitlines()
    assert len(lines) < 200, f"train_qlora.py exceeded 200-line limit: {len(lines)} lines"
