# Compressed Model Assets

This directory contains compressed model files that are small enough for a normal
GitHub repository.

| Archive | Extracts to | Status |
| --- | --- | --- |
| `yolov8m-seg.7z` | `fea_data/yolov8m-seg.pt` | Included. |
| `illumination_robust_model.7z` | `fea_data/illumination_robust_model.pth` | Included. |

The SAM checkpoint is not included. In the local project,
`sam_vit_b_01ec64.pth` is 375 MB and still 335 MB after 7z compression, which is
above GitHub's 100 MB per-file limit for normal Git repositories.

After cloning, extract the included archives into `fea_data/` and place the SAM
checkpoint there manually:

```powershell
7z x model_assets\yolov8m-seg.7z -ofea_data
7z x model_assets\illumination_robust_model.7z -ofea_data
```
