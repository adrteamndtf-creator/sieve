import os
import cv2
import numpy as np

def preprocess_mesh_image(
    image_path: str,
    output_dir: str,
    run_id: int,
    image_idx: int,
    nominal_size_um: float = None,
    pixels_per_mm: float = None
) -> tuple[str, str, str, np.ndarray]:
    """
    Preprocesses a sieve mesh image:
    1. Grayscale conversion
    2. Otsu thresholding
    3. Auto polarity correction (ensures holes are white, wires are black)
    4. Connected-component noise filtering
    5. Saves intermediate images for UI display (Original, Otsu, Filtered)
    
    Returns (orig_preview_path, otsu_preview_path, filtered_preview_path, filtered_binary_img).
    """
    # Create preview output directory if it doesn't exist
    os.makedirs(output_dir, exist_ok=True)
    
    # Read the image
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not read image from path: {image_path}")
        
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # 2. Otsu thresholding (Replicating paper Fig 5b step)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    
    # 3. Auto Polarity Check
    # We want a mask where holes are white (255) and wires are black (0).
    # Sieve mesh has many isolated holes (disconnected components) vs. a single grid of wire.
    # To prevent tiny noise/dust components from skewing the count, we only count
    # components that have a minimum area (e.g. 10 pixels).
    num_labels_normal, _, stats_normal, _ = cv2.connectedComponentsWithStats(thresh, connectivity=8)
    num_labels_inv, _, stats_inv, _ = cv2.connectedComponentsWithStats(255 - thresh, connectivity=8)
    
    valid_count_normal = sum(1 for i in range(1, num_labels_normal) if stats_normal[i, cv2.CC_STAT_AREA] >= 10)
    valid_count_inv = sum(1 for i in range(1, num_labels_inv) if stats_inv[i, cv2.CC_STAT_AREA] >= 10)
    
    if valid_count_inv > valid_count_normal:
        holes_mask = 255 - thresh
        otsu_preview = 255 - thresh
    else:
        holes_mask = thresh
        otsu_preview = thresh

    # 4. Connected-component noise/dirt filtering (Replicating paper Fig 5b -> 5c step)
    # Determine the minimum area threshold for a valid hole.
    # If scale calibration is available, compute nominal hole size in pixels
    min_area_pixels = 15  # Default fallback
    if nominal_size_um is not None and pixels_per_mm is not None:
        # nominal side length in mm
        side_mm = nominal_size_um / 1000.0
        # nominal area in mm^2
        area_mm2 = side_mm ** 2
        # nominal area in pixels
        area_px = area_mm2 * (pixels_per_mm ** 2)
        # Discard components less than 15% of nominal size, or 10 pixels minimum
        min_area_pixels = max(10, int(0.15 * area_px))
    
    # Run labeling on holes_mask
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(holes_mask, connectivity=8)
    
    # Filter mask
    filtered_binary = np.zeros_like(holes_mask)
    for i in range(1, num_labels):  # Skip background (label 0)
        area = stats[i, cv2.CC_STAT_AREA]
        if area >= min_area_pixels:
            filtered_binary[labels == i] = 255
            
    # 5. Save preview images
    orig_name = f"preview_{run_id}_{image_idx}_1_original.png"
    otsu_name = f"preview_{run_id}_{image_idx}_2_otsu.png"
    filt_name = f"preview_{run_id}_{image_idx}_3_filtered.png"
    
    orig_path = os.path.join(output_dir, orig_name)
    otsu_path = os.path.join(output_dir, otsu_name)
    filt_path = os.path.join(output_dir, filt_name)
    
    # Write files (compression level 3 for fast saving)
    cv2.imwrite(orig_path, img, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    cv2.imwrite(otsu_path, otsu_preview, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    cv2.imwrite(filt_path, filtered_binary, [cv2.IMWRITE_PNG_COMPRESSION, 3])
    
    return orig_path, otsu_path, filt_path, filtered_binary
