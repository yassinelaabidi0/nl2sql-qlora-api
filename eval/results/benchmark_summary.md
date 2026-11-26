# NL-to-SQL 3-Way Evaluation Summary

- **Dataset Mode:** `spider` (1034 validation examples)
- **Mock Inference:** `False` | **Timeout:** `3.0s`

| Mode | EX (%) | Valid SQL (%) | Raw Valid SQL (%) | P50 Latency (ms) | P95 Latency (ms) | Peak VRAM (MB) |
| :--- | ---: | ---: | ---: | ---: | ---: | ---: |
| `base_zero_shot` | 53.68 | 83.17 | 83.17 | 2774.77 | 5386.83 | 2172.88 |
| `base_3_shot` | 51.06 | 81.82 | 81.82 | 3687.51 | 6538.00 | 2684.80 |
| `qlora_finetuned` | 70.12 | 91.10 | 91.10 | 3187.21 | 9793.53 | 2285.94 |
