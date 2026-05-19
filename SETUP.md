# Setup Guide

Install FrameSight on **Windows 10/11** for local training and the live detection overlay.

---

## What you need

| Requirement | Notes |
|-------------|--------|
| Windows 10 or 11 | macOS/Linux are not supported |
| Python 3.10+ | [python.org](https://www.python.org/downloads/) — enable **Add Python to PATH** |
| NVIDIA GPU | Strongly recommended for training and real-time inference |
| CUDA drivers | Install/update from [NVIDIA](https://www.nvidia.com/Download/index.aspx) if training fails on GPU |
| Dataset folder | `fn.v1i.yolov8/` in the project root (see below) |

---

## 1. Get the project

**Option A — Git clone**

```powershell
git clone https://github.com/YOUR_USERNAME/FrameSight.git
cd FrameSight
```

**Option B — Download ZIP**

Extract the repo, then open PowerShell in that folder:

```powershell
cd C:\path\to\FrameSight
```

---

## 2. Get the dataset

The dataset is **not** in git (~10k images). You need the YOLOv8 export locally.

1. Download from [Roboflow Universe — fn-ib9mp](https://universe.roboflow.com/itsanoriot/fn-ib9mp/dataset/1)  
   Format: **YOLOv8**
2. Extract so the project looks like this:

```
FrameSight/
  fn.v1i.yolov8/
    data.yaml
    train/
      images/
      labels/
    valid/
      images/
      labels/
    test/          (optional)
```

3. Confirm `fn.v1i.yolov8\train\images` has thousands of `.jpg` files.

**Classes:** `enemy`, `enemy_head`

---

## 3. Run the setup script

In PowerShell (as a normal user):

```powershell
cd C:\path\to\FrameSight
.\scripts\setup_windows.ps1
```

This will:

- Create a virtual environment at `.venv\`
- Install packages from `requirements.txt` (Ultralytics, dxcam, OpenCV, etc.)

If you see **“execution of scripts is disabled”**:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then run `setup_windows.ps1` again.

---

## 4. Verify the install

```powershell
.\.venv\Scripts\Activate.ps1
python -c "import ultralytics, dxcam; print('OK')"
```

You should see `OK`. If `dxcam` or CUDA errors appear, fix drivers/Python before training.

Check the dataset:

```powershell
Test-Path fn.v1i.yolov8\data.yaml
Test-Path fn.v1i.yolov8\train\images
```

Both should return `True`.

---

## 5. Optional configuration

Copy optional overrides:

```powershell
copy config\local.yaml.example config\local.yaml
```

Edit `config\local.yaml` or `config\default.yaml`:

| Setting | File | Purpose |
|---------|------|---------|
| `model.device` | `default.yaml` | `"0"` = first GPU, `"cpu"` = CPU only |
| `training.batch` | `default.yaml` | Lower (e.g. `8`) if you run out of VRAM |
| `training.epochs` | `default.yaml` | Default `100` |

---

## Troubleshooting setup

### `Python was not found`

- Reinstall Python and check **Add to PATH**, or use the `py` launcher:
  ```powershell
  py -3.11 -m venv .venv
  ```

### `pip install` fails on dxcam / torch

- Update pip: `python -m pip install --upgrade pip`
- Install [Visual C++ Redistributable](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist)

### Dataset not found when training

- Folder must be named exactly `fn.v1i.yolov8` at the project root (same level as `scripts\`, `src\`).

### No NVIDIA GPU

- Training on CPU is possible but very slow. Set `model.device: "cpu"` in `config/default.yaml`.

---

## Next step

→ **[TRAIN.md](TRAIN.md)** — train the model and run the overlay.
