# Runtime Model Assets

Large runtime artifacts are intentionally excluded from this public repository.
Place local model and feature files in this directory before running inference.

Expected local files:

| File | Purpose |
| --- | --- |
| `yolov8m-seg.pt` | YOLOv8 segmentation model used to locate dogs. |
| `sam_vit_b_01ec64.pth` | Segment Anything checkpoint for mask refinement. |
| `illumination_robust_model.pth` | ReID backbone checkpoint with illumination-robust training. |
| `universal_features_h.npy` | Dog gallery feature database for identity matching. |

You can override these paths with `YOLO_MODEL_PATH`, `SAM_CHECKPOINT_PATH`,
`REID_MODEL_PATH`, and `DOG_FEATURES_PATH`.
