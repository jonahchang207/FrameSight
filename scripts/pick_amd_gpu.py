#!/usr/bin/env python3
"""Print the ROCm device index of the discrete AMD GPU (prefers the RX 7600 XT).

Output lines (parsed by scripts\\train_gpu.ps1):
  NO_TORCH            torch not importable
  NO_ROCM             torch present but not a ROCm/HIP build that sees a GPU
  DEV <i>: <name>     one line per visible device
  PICK=<i>            chosen device index (-1 if no name matched 'preferred')
  HIP=<version>
"""

from __future__ import annotations

import sys

PREFERRED = "7600"


def main() -> int:
    try:
        import torch
    except Exception:
        print("NO_TORCH")
        return 0

    if not (getattr(torch.version, "hip", None) and torch.cuda.is_available()):
        print("NO_ROCM")
        return 0

    pick = -1
    for i in range(torch.cuda.device_count()):
        name = torch.cuda.get_device_name(i)
        print(f"DEV {i}: {name}")
        if PREFERRED in name and pick < 0:
            pick = i

    print(f"PICK={pick}")
    print(f"HIP={torch.version.hip}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
