import math

def calculate_pixels_per_mm(x1: float, y1: float, x2: float, y2: float, known_distance_mm: float) -> tuple[float, float]:
    """
    Computes pixels-per-mm conversion factor using coordinates of two reference points.
    Returns (pixels_per_mm, pixel_distance).
    """
    pixel_distance = math.sqrt((x2 - x1)**2 + (y2 - y1)**2)
    if known_distance_mm <= 0:
        raise ValueError("Known distance must be greater than zero.")
    if pixel_distance <= 0:
        raise ValueError("Selected points must be different.")
    
    pixels_per_mm = pixel_distance / known_distance_mm
    return pixels_per_mm, pixel_distance
