"""QLoRA fine-tuning script for Qwen2.5-3B-Instruct on schema-disjoint Spider JSONL."""

from __future__ import annotations

import argparse
import inspect
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import torch
import transformers
import yaml
from datasets import Dataset, load_dataset
from packaging.version import Version
from peft import LoraConfig, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

from training.prepare_dataset import assert_disjoint_db_ids


@dataclass(frozen=True)
class PrecisionSpec:
    compute_dtype: torch.dtype
    use_bf16: bool
    use_fp16: bool
    use_quantization: bool
    label: str


def load_config(config_path: Path) -> dict[str, Any]:
    """Load training YAML configuration."""
    return dict(yaml.safe_load(config_path.read_text(encoding="utf-8")))


def is_native_bf16_supported() -> bool:
    """Return True only when CUDA hardware supports native (non-emulated) bfloat16."""
    if not torch.cuda.is_available():
        return False
    if "including_emulation" in inspect.signature(torch.cuda.is_bf16_supported).parameters:
        return bool(torch.cuda.is_bf16_supported(including_emulation=False))
    return torch.cuda.get_device_capability()[0] >= 8 and bool(torch.cuda.is_bf16_supported())


def resolve_precision(cfg: Mapping[str, Any], use_cuda: bool, bf16_supported: bool, dry_run: bool) -> PrecisionSpec:
    """Resolve compute dtype, mixed-precision flags, and 4-bit quantization mode."""
    q_cfg, t_cfg = cfg["quantization"], cfg["training"]
    if not use_cuda:
        if not dry_run:
            raise RuntimeError("QLoRA training requires a CUDA GPU. Pass --dry-run for CPU verification.")
        return PrecisionSpec(torch.float32, False, False, False, "float32-cpu-dry-run")
    quantize = bool(q_cfg.get("load_in_4bit", True))
    if bool(t_cfg.get("bf16", True)) and bf16_supported:
        name = str(q_cfg.get("bnb_4bit_compute_dtype", "bfloat16"))
        return PrecisionSpec(getattr(torch, name), True, False, quantize, name)
    if bool(t_cfg.get("fp16_fallback", True)):
        name = str(q_cfg.get("bnb_4bit_compute_dtype_fallback", "float16"))
        return PrecisionSpec(getattr(torch, name), False, True, quantize, name)
    return PrecisionSpec(torch.float32, False, False, quantize, "float32")


def cast_bfloat16_for_fp16(model: torch.nn.Module) -> None:
    """Cast remaining bfloat16 params for AMP GradScaler compatibility under fp16."""
    for param in model.parameters():
        if param.dtype == torch.bfloat16:
            param.data = param.data.to(torch.float32 if param.requires_grad else torch.float16)


def build_bnb_config(q_cfg: Mapping[str, Any], compute_dtype: torch.dtype) -> BitsAndBytesConfig:
    """Create 4-bit NF4 double-quantization BitsAndBytesConfig."""
    return BitsAndBytesConfig(load_in_4bit=bool(q_cfg["load_in_4bit"]), bnb_4bit_quant_type=str(q_cfg["bnb_4bit_quant_type"]), bnb_4bit_use_double_quant=bool(q_cfg["bnb_4bit_use_double_quant"]), bnb_4bit_compute_dtype=compute_dtype)


def build_lora_config(l_cfg: Mapping[str, Any]) -> LoraConfig:
    """Create QLoRA adapter configuration across configured linear layers."""
    return LoraConfig(r=int(l_cfg["r"]), lora_alpha=int(l_cfg["lora_alpha"]), lora_dropout=float(l_cfg["lora_dropout"]), bias=str(l_cfg["bias"]), task_type=str(l_cfg["task_type"]), target_modules=[str(m) for m in l_cfg["target_modules"]])


def build_sft_config(
    t_cfg: Mapping[str, Any], precision: PrecisionSpec, output_dir: Path, smoketest: bool, dry_run: bool
) -> SFTConfig:
    """Build TRL SFTConfig with completion-only loss and v4/v5 field compatibility."""
    fields = SFTConfig.__dataclass_fields__
    ckpt = "activation" if "activation_checkpointing" in fields else "gradient"
    kwargs: dict[str, Any] = {
        "output_dir": str(output_dir),
        "optim": str(t_cfg["optim"]) if precision.use_quantization else "adamw_torch",
        "lr_scheduler_type": str(t_cfg["lr_scheduler_type"]),
        "learning_rate": float(t_cfg["learning_rate"]),
        "num_train_epochs": 1 if dry_run else int(t_cfg["num_train_epochs"]),
        "per_device_train_batch_size": int(t_cfg["per_device_train_batch_size"]),
        "per_device_eval_batch_size": int(t_cfg["per_device_eval_batch_size"]),
        "gradient_accumulation_steps": 1 if dry_run else int(t_cfg["gradient_accumulation_steps"]),
        "bf16": precision.use_bf16, "fp16": precision.use_fp16,
        f"{ckpt}_checkpointing": True, f"{ckpt}_checkpointing_kwargs": {"use_reentrant": False},
        "completion_only_loss": bool(t_cfg.get("completion_only_loss", True)),
        "max_length": int(t_cfg["max_length"]),
        "logging_steps": 1 if (smoketest or dry_run) else int(t_cfg["logging_steps"]),
        "eval_strategy": "steps" if smoketest else ("no" if dry_run else str(t_cfg["eval_strategy"])),
        "save_strategy": "no" if (smoketest or dry_run) else str(t_cfg["save_strategy"]),
        "seed": int(t_cfg["seed"]), "report_to": [],
        ("warmup_ratio" if "warmup_ratio" in fields else "warmup_steps"): float(t_cfg["warmup_ratio"]),
    }
    if "use_cpu" in fields and not torch.cuda.is_available() and dry_run:
        kwargs["use_cpu"] = True
    if smoketest:
        kwargs.update({"max_steps": 10, "eval_steps": 10})
    return SFTConfig(**kwargs)


def load_prompt_completion_splits(train_path: Path, val_path: Path) -> tuple[Dataset, Dataset]:
    """Load JSONL splits, verify zero db_id overlap, and retain prompt/completion."""
    for p in (train_path, val_path):
        if not p.is_file():
            raise FileNotFoundError(f"Dataset file not found: {p}")
    ds = load_dataset("json", data_files={"train": str(train_path), "validation": str(val_path)})
    train_ds, val_ds = ds["train"], ds["validation"]
    if "db_id" in train_ds.column_names and "db_id" in val_ds.column_names:
        assert_disjoint_db_ids([{"db_id": d} for d in train_ds["db_id"]], [{"db_id": d} for d in val_ds["db_id"]])
    return train_ds.select_columns(["prompt", "completion"]), val_ds.select_columns(["prompt", "completion"])


def resolve_dataset_paths(cfg: Mapping[str, Any], smoketest: bool, dry_run: bool, train_file: Path | None, val_file: Path | None) -> tuple[Path, Path]:
    """Resolve train/val JSONL paths, falling back to smoketest files during dry-run."""
    d_cfg = cfg["dataset"]
    proc_dir = Path(d_cfg["output_dir"])
    use_smoke = smoketest or (dry_run and not (proc_dir / str(d_cfg["train_filename"])).is_file())
    base_dir = Path(d_cfg["smoketest_output_dir"]) if use_smoke else proc_dir
    return train_file or (base_dir / str(d_cfg["train_filename"])), val_file or (base_dir / str(d_cfg["val_filename"]))


def verify_collated_batch(trainer: SFTTrainer) -> dict[str, int]:
    """Inspect one collated training batch to confirm prompt masking (-100) works."""
    batch = next(iter(trainer.get_train_dataloader()))
    assert "labels" in batch, "Collated batch missing 'labels' tensor."
    labels, attn = batch["labels"], batch["attention_mask"]
    masked, unmasked = int(((labels == -100) & (attn == 1)).sum().item()), int((labels != -100).sum().item())
    assert masked > 0, "Expected non-padding prompt tokens to be masked with -100."
    assert unmasked > 0, "Expected completion SQL tokens to remain unmasked."
    return {"batch_size": int(labels.shape[0]), "seq_len": int(labels.shape[1]), "masked_tokens": masked, "unmasked_tokens": unmasked}


def run_training(
    cfg: Mapping[str, Any], train_path: Path, val_path: Path, output_dir: Path,
    model_override: str | None = None, smoketest: bool = False, dry_run: bool = False,
) -> dict[str, Any]:
    """Execute QLoRA training or CPU --dry-run verification and save JSON summary."""
    use_cuda = torch.cuda.is_available()
    precision = resolve_precision(cfg, use_cuda, is_native_bf16_supported(), dry_run)
    model_id, trust_remote = model_override or str(cfg["model"]["base_model_id"]), bool(cfg["model"].get("trust_remote_code", False))
    train_ds, val_ds = load_prompt_completion_splits(train_path, val_path)
    tokenizer = AutoTokenizer.from_pretrained(model_id, trust_remote_code=trust_remote)
    tokenizer.pad_token, tokenizer.padding_side = tokenizer.pad_token or tokenizer.eos_token, "right"
    dtype_kw = "dtype" if Version(transformers.__version__).release[:2] >= (4, 56) else "torch_dtype"
    load_kwargs: dict[str, Any] = {"trust_remote_code": trust_remote, dtype_kw: precision.compute_dtype}
    if precision.use_quantization:
        load_kwargs.update({"quantization_config": build_bnb_config(cfg["quantization"], precision.compute_dtype), "device_map": "auto"})
    model = AutoModelForCausalLM.from_pretrained(model_id, **load_kwargs)
    if precision.use_quantization:
        model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    sft_config = build_sft_config(cfg["training"], precision, output_dir, smoketest, dry_run)
    trainer = SFTTrainer(model=model, args=sft_config, train_dataset=train_ds, eval_dataset=val_ds, peft_config=build_lora_config(cfg["lora"]), processing_class=tokenizer)
    if precision.compute_dtype == torch.float16:
        cast_bfloat16_for_fp16(trainer.model)
    output_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, Any] = {"mode": "dry-run" if dry_run else ("smoketest" if smoketest else "train"), "model_id": model_id, "precision": precision.label, "quantized_4bit": precision.use_quantization, "completion_only_loss": bool(sft_config.completion_only_loss)}
    if dry_run:
        summary["batch_verification"] = verify_collated_batch(trainer)
    else:
        if use_cuda:
            torch.cuda.reset_peak_memory_stats()
        train_res, eval_res = trainer.train(), trainer.evaluate()
        trainer.save_model(str(output_dir))
        tokenizer.save_pretrained(str(output_dir))
        summary.update({"global_step": int(train_res.global_step), "train_loss": float(train_res.training_loss), "eval_loss": float(eval_res["eval_loss"]) if "eval_loss" in eval_res else None, "peak_vram_mb": round(torch.cuda.max_memory_allocated() / (1024**2), 2) if use_cuda else None})
    (output_dir / "training_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="QLoRA fine-tuning for NL-to-SQL with TRL SFTTrainer.")
    parser.add_argument("--config", type=Path, default=Path("training/config.yaml"))
    parser.add_argument("--smoketest", action="store_true", help="Run 10-step smoketest on smoketest JSONL.")
    parser.add_argument("--dry-run", action="store_true", help="Validate config, tokenization, and -100 masking.")
    for flag, typ in (("--model-override", str), ("--output-dir", Path), ("--train-file", Path), ("--val-file", Path)):
        parser.add_argument(flag, type=typ, default=None)
    args = parser.parse_args(list(argv) if argv is not None else None)
    cfg = load_config(args.config)
    train_path, val_path = resolve_dataset_paths(cfg, args.smoketest, args.dry_run, args.train_file, args.val_file)
    print(json.dumps(run_training(cfg, train_path, val_path, args.output_dir or Path(cfg["training"]["output_dir"]), args.model_override, args.smoketest, args.dry_run), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
