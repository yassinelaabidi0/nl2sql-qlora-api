"""3-way greedy evaluation harness (zero-shot, 3-shot, QLoRA) on Spider val splits."""

from __future__ import annotations

import argparse
import gc
import json
import logging
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from contextlib import nullcontext
from pathlib import Path
from typing import Any

import yaml

from eval.sqlite_exec import evaluate_prediction
from training import prepare_dataset as prep

logger = logging.getLogger(__name__)
MODES = ("base_zero_shot", "base_3_shot", "qlora_finetuned")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    """Read UTF-8 JSONL rows from disk."""
    return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


def percentile(values: Sequence[float], pct: float) -> float:
    """Compute linear-interpolated percentile for a non-empty sequence."""
    ordered = sorted(values)
    pos = (len(ordered) - 1) * (pct / 100.0)
    lo, hi = int(pos), min(int(pos) + 1, len(ordered) - 1)
    return float(ordered[lo] + (pos - lo) * (ordered[hi] - ordered[lo]))


def select_few_shot_examples(train_rows: Sequence[Mapping[str, Any]], val_rows: Sequence[Mapping[str, Any]], k: int = 3) -> list[dict[str, Any]]:
    """Select k deterministic schema-disjoint examples from the training split."""
    selected, seen, used = [], set(), set()
    for idx, row in enumerate(train_rows):
        if str(row["db_id"]) not in seen and len(selected) < k:
            selected.append(dict(row)); seen.add(str(row["db_id"])); used.add(idx)
    for idx, row in enumerate(train_rows):
        if len(selected) < k and idx not in used: selected.append(dict(row))
    if len(selected) < k:
        raise ValueError(f"Need at least {k} training examples for {k}-shot prompting, got {len(selected)}.")
    prep.assert_disjoint_db_ids(selected, val_rows)
    return selected


def build_3shot_prompt(system_msg: Mapping[str, str], few_shot: Sequence[Mapping[str, Any]], user_msg: Mapping[str, str]) -> list[dict[str, str]]:
    """Assemble [system, (user, assistant)*3, target_user] chat messages."""
    return [dict(system_msg), *[dict(m) for ex in few_shot for m in (ex["prompt"][1], ex["completion"][0])], dict(user_msg)]


def generate_sql_greedy(model: Any, tokenizer: Any, messages: Sequence[Mapping[str, str]], max_new_tokens: int = 256) -> tuple[str, float]:
    """Run deterministic greedy decoding and return (raw_sql, latency_ms)."""
    import torch

    t0 = time.perf_counter()
    enc = tokenizer.apply_chat_template(list(messages), add_generation_prompt=True, tokenize=True, return_tensors="pt")
    input_ids = enc["input_ids"] if isinstance(enc, Mapping) else enc
    attn = enc["attention_mask"] if isinstance(enc, Mapping) and "attention_mask" in enc else torch.ones_like(input_ids)
    dev = next(model.parameters()).device
    with torch.inference_mode():
        out = model.generate(input_ids=input_ids.to(dev), attention_mask=attn.to(dev), max_new_tokens=max_new_tokens, do_sample=False, temperature=None, top_p=None, top_k=None, pad_token_id=tokenizer.pad_token_id)
    return str(tokenizer.decode(out[0, input_ids.shape[-1]:], skip_special_tokens=True)), (time.perf_counter() - t0) * 1000.0


def mock_generate_sql(mode: str, row: Mapping[str, Any], idx: int) -> tuple[str, float]:
    """Deterministic CPU stub returning candidate SQL strings for offline verification."""
    t0 = time.perf_counter()
    gold = str(row["completion"][0]["content"])
    if mode == "base_zero_shot":
        pred = "SELECT nonexistent_column FROM missing_table" if idx % 4 == 3 else (f"```sql\n{gold}\n```" if idx % 2 == 0 else gold)
    else:
        pred = "SELECT 1 WHERE 0 = 1" if (mode == "base_3_shot" and idx % 5 == 4) else gold
    return pred, (time.perf_counter() - t0) * 1000.0


def load_hf_model_and_tokenizer(cfg: Mapping[str, Any], adapter_dir: Path | str | None = None) -> tuple[Any, Any]:
    """Load base Qwen2.5 model (4-bit NF4 on CUDA) and optional LoRA adapter."""
    import torch
    import transformers
    from packaging.version import Version
    from peft import PeftModel
    from transformers import AutoModelForCausalLM, AutoTokenizer

    from training import train_qlora as tq

    use_cuda = torch.cuda.is_available()
    precision = tq.resolve_precision(cfg, use_cuda, tq.is_native_bf16_supported(), dry_run=not use_cuda)
    model_id, trust = str(cfg["model"]["base_model_id"]), bool(cfg["model"].get("trust_remote_code", False))
    tok = AutoTokenizer.from_pretrained(model_id, trust_remote_code=trust)
    tok.pad_token = tok.pad_token or tok.eos_token
    dtype_kw = "dtype" if Version(transformers.__version__).release[:2] >= (4, 56) else "torch_dtype"
    load_kw: dict[str, Any] = {"trust_remote_code": trust, dtype_kw: precision.compute_dtype}
    if precision.use_quantization:
        load_kw.update({"quantization_config": tq.build_bnb_config(cfg["quantization"], precision.compute_dtype), "device_map": "auto"})
    model = AutoModelForCausalLM.from_pretrained(model_id, **load_kw)
    if adapter_dir is not None:
        model = PeftModel.from_pretrained(model, str(adapter_dir))
    model.eval()
    return model, tok


def evaluate_mode(
    mode: str, val_rows: Sequence[Mapping[str, Any]], few_shot: Sequence[Mapping[str, Any]],
    db_dir: Path, predictor: Callable[[Sequence[Mapping[str, str]], Mapping[str, Any], int], tuple[str, float]],
    timeout_sec: float, measure_vram: bool,
) -> dict[str, Any]:
    """Evaluate one mode across validation rows and compute EX/valid/latency/VRAM metrics."""
    torch_mod = __import__("torch") if measure_vram else None
    has_cuda = bool(torch_mod and torch_mod.cuda.is_available())
    if has_cuda:
        torch_mod.cuda.reset_peak_memory_stats()
    ex_hits, clean_valid, raw_valid, fenced, latencies = 0, 0, 0, 0, []
    for idx, row in enumerate(val_rows):
        msgs = build_3shot_prompt(row["prompt"][0], few_shot, row["prompt"][1]) if mode == "base_3_shot" else row["prompt"]
        raw_pred, elapsed_ms = predictor(msgs, row, idx)
        latencies.append(elapsed_ms)
        cmp = evaluate_prediction(prep.resolve_sqlite_path(db_dir, str(row["db_id"])), raw_pred, str(row["completion"][0]["content"]), timeout_sec)
        ex_hits, clean_valid, raw_valid, fenced = ex_hits + int(cmp.exact_match), clean_valid + int(cmp.cleaned_valid), raw_valid + int(cmp.raw_valid), fenced + int(cmp.had_markdown_fence)
        if not cmp.cleaned_valid:
            logger.debug("%s idx=%d db=%s raw_valid=%s error=%s", mode, idx, row["db_id"], cmp.raw_valid, cmp.pred_error)
    n = len(val_rows)
    return {
        "mode": mode, "total_examples": n, "execution_accuracy_pct": round(100.0 * ex_hits / n, 2),
        "valid_sql_rate_pct": round(100.0 * clean_valid / n, 2), "raw_valid_sql_rate_pct": round(100.0 * raw_valid / n, 2),
        "fenced_outputs": fenced, "latency_p50_ms": round(percentile(latencies, 50.0), 2),
        "latency_p95_ms": round(percentile(latencies, 95.0), 2),
        "peak_vram_mb": round(torch_mod.cuda.max_memory_allocated() / (1024**2), 2) if has_cuda else 0.0,
    }


def render_markdown_summary(report: Mapping[str, Any]) -> str:
    """Format benchmark summary JSON into a Markdown comparison table."""
    hdr = f"# NL-to-SQL 3-Way Evaluation Summary\n\n- **Dataset Mode:** `{report['mode']}` ({report['num_examples']} validation examples)\n- **Mock Inference:** `{report['mock_inference']}` | **Timeout:** `{report['timeout_sec']}s`\n\n| Mode | EX (%) | Valid SQL (%) | Raw Valid SQL (%) | P50 Latency (ms) | P95 Latency (ms) | Peak VRAM (MB) |\n| :--- | ---: | ---: | ---: | ---: | ---: | ---: |"
    rows = [f"| `{r['mode']}` | {r['execution_accuracy_pct']:.2f} | {r['valid_sql_rate_pct']:.2f} | {r['raw_valid_sql_rate_pct']:.2f} | {r['latency_p50_ms']:.2f} | {r['latency_p95_ms']:.2f} | {r['peak_vram_mb']:.2f} |" for r in report["results"]]
    return "\n".join([hdr, *rows]) + "\n"


def run_benchmark(
    cfg: Mapping[str, Any], smoketest: bool, mock_inference: bool, output_dir: Path,
    train_file: Path | None = None, val_file: Path | None = None, db_dir: Path | None = None,
    adapter_dir: Path | None = None, max_examples: int | None = None, timeout_sec: float = 3.0,
) -> dict[str, Any]:
    """Run all 3 evaluation modes and persist JSON + Markdown benchmark reports."""
    d_cfg = cfg["dataset"]
    base_dir = Path(d_cfg["smoketest_output_dir"] if smoketest else d_cfg["output_dir"])
    t_path, v_path = train_file or (base_dir / str(d_cfg["train_filename"])), val_file or (base_dir / str(d_cfg["val_filename"]))
    with (tempfile.TemporaryDirectory(prefix="eval_smoketest_") if smoketest else nullcontext()) as tmp_dir:
        raw_recs, smoke_db = prep.generate_smoketest_data(Path(tmp_dir)) if smoketest else ([], Path())
        eff_db_dir = db_dir or (smoke_db if smoketest else Path(d_cfg["spider_db_dir"]))
        if smoketest and not (t_path.is_file() and v_path.is_file()):
            tr_raw, va_raw = prep.split_by_db_id(raw_recs, float(d_cfg["val_ratio"]), int(d_cfg["seed"]))
            cache: dict[str, str] = {}
            train_rows, val_rows = [dict(x) for x in prep.format_split(tr_raw, eff_db_dir, cache)], [dict(x) for x in prep.format_split(va_raw, eff_db_dir, cache)]
        else:
            train_rows, val_rows = read_jsonl(t_path), read_jsonl(v_path)
        val_rows = val_rows[:max_examples] if max_examples is not None else val_rows
        prep.assert_disjoint_db_ids(train_rows, val_rows)
        few_shot = select_few_shot_examples(train_rows, val_rows, k=3)
        eff_adapter = adapter_dir or Path(cfg["training"]["output_dir"])
        if mock_inference:
            results = [evaluate_mode(m, val_rows, few_shot, eff_db_dir, lambda _m, r, i, md=m: mock_generate_sql(md, r, i), timeout_sec, False) for m in MODES]
        else:
            import torch
            if not eff_adapter.is_dir():
                raise FileNotFoundError(f"Adapter directory not found: {eff_adapter}")
            base_model, tok = load_hf_model_and_tokenizer(cfg, None)
            results = [evaluate_mode(m, val_rows, few_shot, eff_db_dir, lambda msgs, _r, _i: generate_sql_greedy(base_model, tok, msgs), timeout_sec, True) for m in MODES[:2]]
            del base_model
            gc.collect()
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
            ft_model, ft_tok = load_hf_model_and_tokenizer(cfg, eff_adapter)
            results.append(evaluate_mode("qlora_finetuned", val_rows, few_shot, eff_db_dir, lambda msgs, _r, _i: generate_sql_greedy(ft_model, ft_tok, msgs), timeout_sec, True))
    report = {"mode": "smoketest" if smoketest else "spider", "mock_inference": mock_inference, "num_examples": len(val_rows), "timeout_sec": timeout_sec, "results": results}
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "benchmark_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (output_dir / "benchmark_summary.md").write_text(render_markdown_summary(report), encoding="utf-8")
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate zero-shot, 3-shot, and QLoRA NL-to-SQL models.")
    for flag in ("--smoketest", "--mock-inference"): parser.add_argument(flag, action="store_true")
    for flag, default in (("--config", Path("training/config.yaml")), ("--output-dir", Path("eval/results")), ("--train-file", None), ("--val-file", None), ("--db-dir", None), ("--adapter-dir", None)): parser.add_argument(flag, type=Path, default=default)
    for flag, typ, default in (("--max-examples", int, None), ("--timeout-sec", float, 3.0)): parser.add_argument(flag, type=typ, default=default)
    args = parser.parse_args(list(argv) if argv is not None else None)
    cfg = dict(yaml.safe_load(args.config.read_text(encoding="utf-8")))
    print(json.dumps(run_benchmark(cfg, args.smoketest, args.mock_inference, args.output_dir, args.train_file, args.val_file, args.db_dir, args.adapter_dir, args.max_examples, args.timeout_sec), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
