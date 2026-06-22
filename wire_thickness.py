import numpy as np
import cv2
from scipy.signal import find_peaks, peak_widths

def rotate_image(image: np.ndarray, angle: float) -> np.ndarray:
    """Rotates an image by a given angle in degrees around its center."""
    h, w = image.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    # Using INTER_NEAREST for binary image rotation to preserve binary values
    return cv2.warpAffine(image, M, (w, h), flags=cv2.INTER_NEAREST, borderMode=cv2.BORDER_CONSTANT, borderValue=0)

def find_optimal_rotation_angle(binary_img: np.ndarray) -> float:
    """
    Finds the optimal grid alignment angle between -45 and +45 degrees (step 0.5).
    Replicates the paper's method of finding alignment by maximizing projection peaks/variance.
    Using variance is highly robust as aligned grids produce sharp spikes and flat valleys.
    """
    # Resize to speed up the grid rotation sweep (crucial performance optimization)
    resize_dim = 400
    h, w = binary_img.shape[:2]
    scale = resize_dim / max(h, w)
    new_w, new_h = int(w * scale), int(h * scale)
    small_img = cv2.resize(binary_img, (new_w, new_h), interpolation=cv2.INTER_NEAREST)
    
    angles = np.arange(-45.0, 45.1, 0.5)
    best_angle = 0.0
    max_variance = -1.0
    
    for angle in angles:
        rotated = rotate_image(small_img, angle)
        # Compute horizontal and vertical projections
        proj_h = np.sum(rotated, axis=1)
        proj_v = np.sum(rotated, axis=0)
        
        # Total variance as a metric for spikiness
        total_var = np.var(proj_h) + np.var(proj_v)
        
        if total_var > max_variance:
            max_variance = total_var
            best_angle = angle
            
    return float(best_angle)

def measure_wire_thickness(
    filtered_holes_binary: np.ndarray,
    pixels_per_mm: float,
    nominal_size_um: float = None
) -> dict:
    """
    Meases wire thickness by finding optimal rotation angle, projecting grid rows and columns,
    detecting peaks, and calculating peak widths.
    """
    # Wires are the background of filtered_holes_binary. 
    # Create wire binary mask (wires = white/255, holes = black/0)
    wires_binary = 255 - filtered_holes_binary
    
    # 1. Find optimal rotation angle
    opt_angle = find_optimal_rotation_angle(wires_binary)
    
    # 2. Rotate full resolution image by the optimal angle
    aligned_wires = rotate_image(wires_binary, opt_angle)
    
    h, w = aligned_wires.shape[:2]
    proj_h = np.sum(aligned_wires, axis=1).astype(float)
    proj_v = np.sum(aligned_wires, axis=0).astype(float)
    
    # Normalize projections for analysis and plotting in UI
    # Raw values are in [0, 255 * dimension], let's scale to [0, 100] representing % density
    proj_h_norm = (proj_h / (255.0 * w)) * 100.0
    proj_v_norm = (proj_v / (255.0 * h)) * 100.0
    
    # Define peak finding parameters
    # A wire peak should stand out. Set prominence to 15% of the range
    prominence_h = 15.0 if np.max(proj_h_norm) > 15.0 else 5.0
    prominence_v = 15.0 if np.max(proj_v_norm) > 15.0 else 5.0
    
    peaks_h, _ = find_peaks(proj_h_norm, prominence=prominence_h)
    peaks_v, _ = find_peaks(proj_v_norm, prominence=prominence_v)
    
    widths_px = []
    
    # Calculate widths at half height (rel_height=0.5)
    if len(peaks_h) > 0:
        w_h, _, _, _ = peak_widths(proj_h_norm, peaks_h, rel_height=0.5)
        widths_px.extend(w_h)
        
    if len(peaks_v) > 0:
        w_v, _, _, _ = peak_widths(proj_v_norm, peaks_v, rel_height=0.5)
        widths_px.extend(w_v)
        
    if not widths_px:
        # Fallback if no peaks detected (highly unusual for mesh, but handles blank images)
        avg_width_px = 5.0
    else:
        # Remove outline measurement anomalies if any
        widths_px = np.array(widths_px)
        # Sieve wires should be uniform, filter out extreme values
        median_w = np.median(widths_px)
        filtered_widths = widths_px[np.abs(widths_px - median_w) < 2 * median_w]
        if len(filtered_widths) > 0:
            avg_width_px = np.mean(filtered_widths)
        else:
            avg_width_px = median_w
            
    avg_thickness_mm = avg_width_px / pixels_per_mm
    
    # Return results including projection profiles for UI plotting (replicates paper Fig 6)
    return {
        "wire_thickness_mm": float(avg_thickness_mm),
        "alignment_angle": opt_angle,
        "horizontal_projection": proj_h_norm.tolist(),
        "vertical_projection": proj_v_norm.tolist(),
        "horizontal_peaks": peaks_h.tolist(),
        "vertical_peaks": peaks_v.tolist(),
    }
