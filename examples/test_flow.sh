#!/usr/bin/env bash
set -euo pipefail
# Example semantic events around an NPU operator test.
npu-observer event npu.test.started --source adapter --attributes '{"operator":"flash_attention_score_grad","shape":{"B":2,"N":32,"S":4096,"D":128},"dtype":"bf16","layout":"TND"}'
sleep 0.05
npu-observer event npu.accuracy.completed --source adapter --attributes '{"operator":"flash_attention_score_grad","cosine":0.99998,"max_abs":0.0021,"pass":true}'
npu-observer event npu.benchmark.completed --source adapter --attributes '{"operator":"flash_attention_score_grad","latency_us":182.4,"mfu":0.831}'
npu-observer event npu.test.completed --source adapter --attributes '{"operator":"flash_attention_score_grad","status":"pass"}'
