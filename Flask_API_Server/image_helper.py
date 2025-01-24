from PIL import Image
import numpy as np

# Define the 7-color palette mapping
default_color_palette = {
    (255, 255, 255): 0xFF,  # White
    (255, 255, 0): 0xFC,    # Yellow
    (255, 0, 0): 0xE0,      # Red
    (0, 128, 0): 0x1c,      # Green
    (0, 0, 255): 0x03,      # Blue
    (0, 0, 0): 0x00         # Black
}

def closest_palette_color(rgb, target_color_palette = default_color_palette):
    """Find the closest color in the palette."""
    min_dist = float('inf')
    closest_color = (255, 255, 255)  # Default to white
    for palette_rgb in target_color_palette:
        # Cast to int32 to prevent overflow during calculations
        dist = sum((int(rgb[i]) - int(palette_rgb[i])) ** 2 for i in range(3))
        if dist < min_dist:
            min_dist = dist
            closest_color = palette_rgb
    return closest_color

def apply_floyd_steinberg_dithering(image, target_color_palette = default_color_palette):
    """Apply Floyd-Steinberg dithering to the image."""
    pixels = np.array(image, dtype=np.int16)  # Use int16 to allow negative values during error distribution
    for y in range(image.height):
        for x in range(image.width):
            old_pixel = tuple(pixels[y, x][:3])
            new_pixel = closest_palette_color(old_pixel, target_color_palette)
            pixels[y, x][:3] = new_pixel
            quant_error = np.array(old_pixel) - np.array(new_pixel)
            
            # Distribute the quantization error to neighboring pixels (convert to int16 before adding)
            if x + 1 < image.width:
                pixels[y, x + 1][:3] += (quant_error * 7 / 16).astype(np.int16)
            if x - 1 >= 0 and y + 1 < image.height:
                pixels[y + 1, x - 1][:3] += (quant_error * 3 / 16).astype(np.int16)
            if y + 1 < image.height:
                pixels[y + 1, x][:3] += (quant_error * 5 / 16).astype(np.int16)
            if x + 1 < image.width and y + 1 < image.height:
                pixels[y + 1, x + 1][:3] += (quant_error * 1 / 16).astype(np.int16)
    
    # Clip pixel values to be within 0-255 range after dithering
    pixels = np.clip(pixels, 0, 255)
    return Image.fromarray(pixels.astype(np.uint8))
    