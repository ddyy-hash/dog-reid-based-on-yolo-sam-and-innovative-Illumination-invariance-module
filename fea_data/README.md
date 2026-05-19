# Runtime Model Assets

Runtime model files should be extracted or placed here before running inference.
The repository includes compressed archives for the smaller YOLOv8 and custom
illumination-robust ReID models under `model_assets/`.

Expected local files:

| File | Purpose |
| --- | --- |
| `yolov8m-seg.pt` | YOLOv8 segmentation model used to locate dogs. |
| `sam_vit_b_01ec64.pth` | Segment Anything checkpoint for mask refinement. |
| `illumination_robust_model.pth` | ReID backbone checkpoint with illumination-robust training. |
| `universal_features_h.npy` | Dog gallery feature database for identity matching. |

Not all assets are tracked in Git:

- `sam_vit_b_01ec64.pth` is too large for a normal GitHub repository.
- `universal_features_h.npy` is a private dog identity feature gallery.

You can override these paths with `YOLO_MODEL_PATH`, `SAM_CHECKPOINT_PATH`,
`REID_MODEL_PATH`, and `DOG_FEATURES_PATH`.
