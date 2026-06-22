import numpy as np
import cv2

def measure_holes(filtered_binary: np.ndarray, pixels_per_mm: float) -> dict:
    """
    Measures sieve hole areas using 8-connected component labeling (Replicating paper Fig 8 stats).
    Applies IQR statistical outlier filtering to remove residual noise/tears.
    Returns a dictionary of statistics and a list of valid hole areas in mm^2.
    """
    num_labels, labels, stats, centroids = cv2.connectedComponentsWithStats(
        filtered_binary, connectivity=8
    )
    
    # Calculate areas for each component (skip background label 0)
    areas_px = []
    for i in range(1, num_labels):
        areas_px.append(stats[i, cv2.CC_STAT_AREA])
        
    if not areas_px:
        return {
            "total_analyzed": 0,
            "area_average": 0.0,
            "shortest_area": 0.0,
            "highest_area": 0.0,
            "area_std": 0.0,
            "valid_areas": [],
            "outliers_count": 0
        }
        
    # Convert to mm^2
    scale_sq = pixels_per_mm ** 2
    areas_mm2 = np.array(areas_px) / scale_sq
    
    # Outlier removal via IQR (Interquartile Range)
    if len(areas_mm2) >= 4:
        q75, q25 = np.percentile(areas_mm2, [75, 25])
        iqr = q75 - q25
        lower_bound = q25 - 1.5 * iqr
        upper_bound = q75 + 1.5 * iqr
        
        valid_mask = (areas_mm2 >= lower_bound) & (areas_mm2 <= upper_bound)
        valid_areas = areas_mm2[valid_mask]
        outliers_count = len(areas_mm2) - len(valid_areas)
    else:
        valid_areas = areas_mm2
        outliers_count = 0
        
    if len(valid_areas) == 0:
        return {
            "total_analyzed": 0,
            "area_average": 0.0,
            "shortest_area": 0.0,
            "highest_area": 0.0,
            "area_std": 0.0,
            "valid_areas": [],
            "outliers_count": len(areas_mm2)
        }
        
    return {
        "total_analyzed": len(valid_areas),
        "area_average": float(np.mean(valid_areas)),
        "shortest_area": float(np.min(valid_areas)),
        "highest_area": float(np.max(valid_areas)),
        "area_std": float(np.std(valid_areas)),
        "valid_areas": valid_areas.tolist(),
        "outliers_count": int(outliers_count)
    }
