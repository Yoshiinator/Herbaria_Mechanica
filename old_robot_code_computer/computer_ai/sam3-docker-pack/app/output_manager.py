"""
Output management for saving results and metadata.
Supports both local filesystem and network storage paths (UNC format).
"""
import os
import json
import time
from pathlib import Path
from typing import Optional, List, Dict, Any
import torch
import numpy as np
from PIL import Image


OUTPUT_DIR = Path("/outputs")


def _is_network_path(path: str) -> bool:
    """Check if path is a network path (UNC format)."""
    return path.startswith('\\\\') or path.startswith('//')


def _ensure_directory_exists(file_path: str) -> None:
    """Ensure the directory for the given file path exists."""
    if _is_network_path(file_path):
        # For network paths, extract directory and create if needed
        # Normalize path separators
        normalized = file_path.replace('/', '\\')
        dir_path = os.path.dirname(normalized)
        if dir_path and not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
            except OSError as e:
                # Network path might not support makedirs, try to continue
                # The actual file write will fail if directory doesn't exist
                pass
    else:
        # Local path - use pathlib
        dir_path = Path(file_path).parent
        dir_path.mkdir(parents=True, exist_ok=True)


async def save_result_image(image_bytes: bytes, output_path: Optional[str] = None) -> str:
    """
    Save result image to disk or network storage.
    
    Args:
        image_bytes: Image data as bytes
        output_path: Optional network storage path (UNC format) or local directory.
                     If None, uses local OUTPUT_DIR.
                     If directory path, creates unique filename in that directory.
                     If full file path, saves to that exact path.
    
    Returns:
        Full path to saved file (network path if output_path was network, else local path)
    """
    timestamp = int(time.time())
    filename = f"result_{timestamp}.png"
    
    if output_path is None:
        # Use local output directory
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_DIR / filename
        filepath_str = str(filepath)
    elif _is_network_path(output_path):
        # Network path - check if it's a directory or full path
        normalized = output_path.replace('/', '\\')
        if normalized.endswith('\\') or os.path.isdir(normalized):
            # It's a directory, append filename
            filepath_str = os.path.join(normalized, filename).replace('/', '\\')
        else:
            # It's a full file path
            filepath_str = normalized
        _ensure_directory_exists(filepath_str)
    else:
        # Local path - check if it's a directory or full path
        if os.path.isdir(output_path) or output_path.endswith('/') or output_path.endswith('\\'):
            # It's a directory, append filename
            filepath_str = os.path.join(output_path, filename)
        else:
            # It's a full file path
            filepath_str = output_path
        _ensure_directory_exists(filepath_str)
    
    # Write the file
    with open(filepath_str, "wb") as f:
        f.write(image_bytes)
    
    return filepath_str


async def save_metadata(
    metadata: dict,
    output_path: Optional[str] = None,
    original_filename: Optional[str] = None
) -> str:
    """
    Save metadata JSON to disk or network storage.
    
    Args:
        metadata: Metadata dictionary to save
        output_path: Optional network storage path (UNC format) or local directory.
                     If None, uses local OUTPUT_DIR.
                     If directory path, creates unique filename in that directory.
                     If full file path, saves to that exact path.
        original_filename: Optional base name (e.g. from input image) to embed in filename.
    
    Returns:
        Full path to saved file (network path if output_path was network, else local path)
    """
    timestamp = int(time.time())
    if original_filename is not None:
        safe_name = _sanitize_filename(original_filename)
        filename = f"metadata_{safe_name}_{timestamp}.json"
    else:
        filename = f"metadata_{timestamp}.json"
    
    if output_path is None:
        # Use local output directory
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        filepath = OUTPUT_DIR / filename
        filepath_str = str(filepath)
    elif _is_network_path(output_path):
        # Network path - check if it's a directory or full path
        normalized = output_path.replace('/', '\\')
        if normalized.endswith('\\') or os.path.isdir(normalized):
            # It's a directory, append filename
            filepath_str = os.path.join(normalized, filename).replace('/', '\\')
        else:
            # It's a full file path
            filepath_str = normalized
        _ensure_directory_exists(filepath_str)
    else:
        # Local path - check if it's a directory or full path
        if os.path.isdir(output_path) or output_path.endswith('/') or output_path.endswith('\\'):
            # It's a directory, append filename
            filepath_str = os.path.join(output_path, filename)
        else:
            # It's a full file path
            filepath_str = output_path
        _ensure_directory_exists(filepath_str)
    
    # Write the file
    with open(filepath_str, "w", encoding="utf-8") as f:
        json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    return filepath_str


async def save_individual_masks(
    masks: torch.Tensor,
    original_image: Image.Image,
    output_path: str,
    timestamp: Optional[int] = None
) -> List[str]:
    """
    Save individual mask images for each detected object.
    
    Args:
        masks: Tensor of masks (shape: [N, H, W] or [1, N, H, W])
        original_image: Original PIL Image for size reference
        output_path: Directory path to save masks
        timestamp: Optional timestamp for filename (uses current time if None)
    
    Returns:
        List of file paths to saved mask images
    """
    if timestamp is None:
        timestamp = int(time.time())
    
    if masks.numel() == 0:
        return []
    
    # Normalize masks tensor
    masks_np = masks.cpu().numpy() if isinstance(masks, torch.Tensor) else masks
    if masks_np.ndim == 3 and masks_np.shape[0] == 1:
        masks_np = masks_np[0]
    elif masks_np.ndim == 4:
        masks_np = masks_np.squeeze(0)
    
    saved_paths = []
    original_size = original_image.size
    
    for i, mask in enumerate(masks_np):
        if mask.ndim == 2:
            # Convert mask to binary (0-255)
            mask_binary = (mask > 0.5).astype(np.uint8) * 255
            
            # Resize mask to original image size if needed
            mask_img = Image.fromarray(mask_binary, mode="L")
            if mask_img.size != original_size:
                mask_img = mask_img.resize(original_size, Image.NEAREST)
            
            # Generate filename
            filename = f"mask_{timestamp}_{i+1}.png"
            
            # Determine full path
            if _is_network_path(output_path):
                normalized = output_path.replace('/', '\\')
                if not normalized.endswith('\\'):
                    normalized += '\\'
                filepath_str = os.path.join(normalized, filename).replace('/', '\\')
            else:
                if not output_path.endswith('/') and not output_path.endswith('\\'):
                    output_path += '/'
                filepath_str = os.path.join(output_path, filename)
            
            _ensure_directory_exists(filepath_str)
            
            # Save mask image
            mask_img.save(filepath_str, "PNG")
            saved_paths.append(filepath_str)
    
    return saved_paths


async def save_cropped_objects(
    boxes: torch.Tensor,
    masks: torch.Tensor,
    original_image: Image.Image,
    output_path: str,
    timestamp: Optional[int] = None
) -> List[str]:
    """
    Save cropped object images extracted using bounding boxes.
    
    Args:
        boxes: Tensor of bounding boxes (shape: [N, 4] with [x0, y0, x1, y1])
        masks: Tensor of masks (for validation, shape: [N, H, W])
        original_image: Original PIL Image to crop from
        output_path: Directory path to save cropped objects
        timestamp: Optional timestamp for filename (uses current time if None)
    
    Returns:
        List of file paths to saved cropped object images
    """
    if timestamp is None:
        timestamp = int(time.time())
    
    if boxes.numel() == 0:
        return []
    
    boxes_np = boxes.cpu().numpy() if isinstance(boxes, torch.Tensor) else boxes
    saved_paths = []
    
    for i, box in enumerate(boxes_np):
        x0, y0, x1, y1 = box
        
        # Ensure coordinates are within image bounds
        x0 = max(0, int(x0))
        y0 = max(0, int(y0))
        x1 = min(original_image.width, int(x1))
        y1 = min(original_image.height, int(y1))
        
        # Skip invalid boxes
        if x1 <= x0 or y1 <= y0:
            continue
        
        # Crop the object from original image
        cropped = original_image.crop((x0, y0, x1, y1))
        
        # Generate filename
        filename = f"object_{timestamp}_{i+1}.png"
        
        # Determine full path
        if _is_network_path(output_path):
            normalized = output_path.replace('/', '\\')
            if not normalized.endswith('\\'):
                normalized += '\\'
            filepath_str = os.path.join(normalized, filename).replace('/', '\\')
        else:
            if not output_path.endswith('/') and not output_path.endswith('\\'):
                output_path += '/'
            filepath_str = os.path.join(output_path, filename)
        
        _ensure_directory_exists(filepath_str)
        
        # Save cropped image
        cropped.save(filepath_str, "PNG")
        saved_paths.append(filepath_str)
    
    return saved_paths


def _sanitize_filename(text: str) -> str:
    """
    Sanitize text for use in filenames.
    
    Args:
        text: Text to sanitize
    
    Returns:
        Sanitized text safe for filenames
    """
    import re
    # Convert to lowercase
    text = text.lower()
    # Replace spaces and multiple spaces with single underscore
    text = re.sub(r'\s+', '_', text)
    # Remove invalid filename characters (keep alphanumeric, underscore, hyphen)
    text = re.sub(r'[^a-z0-9_-]', '', text)
    # Remove multiple underscores
    text = re.sub(r'_+', '_', text)
    # Remove leading/trailing underscores
    text = text.strip('_')
    # If empty after sanitization, use 'object'
    if not text:
        text = 'object'
    # Limit length to avoid filesystem issues
    if len(text) > 50:
        text = text[:50]
    return text


async def save_masked_segments(
    masks: torch.Tensor,
    original_image: Image.Image,
    text_prompt: str,
    output_path: str,
    timestamp: Optional[int] = None
) -> List[str]:
    """
    Save masked segments extracted from the original image.
    Each segment shows only the masked region with transparent background.
    Files are named using the text prompt with instance numbering (e.g., "person_1.png", "person_2.png").
    
    Args:
        masks: Tensor of masks (shape: [N, H, W] or [1, N, H, W])
        original_image: Original PIL Image to extract segments from
        text_prompt: Text prompt used for detection (used in filename)
        output_path: Directory path to save segments
        timestamp: Optional timestamp for filename (uses current time if None)
    
    Returns:
        List of file paths to saved masked segment images
    """
    if timestamp is None:
        timestamp = int(time.time())
    
    if masks.numel() == 0:
        return []
    
    # Normalize masks tensor
    masks_np = masks.cpu().numpy() if isinstance(masks, torch.Tensor) else masks
    if masks_np.ndim == 3 and masks_np.shape[0] == 1:
        masks_np = masks_np[0]
    elif masks_np.ndim == 4:
        masks_np = masks_np.squeeze(0)
    
    saved_paths = []
    original_size = original_image.size
    
    # Sanitize prompt for filename
    sanitized_prompt = _sanitize_filename(text_prompt)
    
    # Convert original image to RGBA if not already
    if original_image.mode != 'RGBA':
        original_rgba = original_image.convert('RGBA')
    else:
        original_rgba = original_image.copy()
    
    # Convert to numpy array for processing
    img_array = np.array(original_rgba)
    
    # Track instance count for naming
    instance_count = 0
    
    for i, mask in enumerate(masks_np):
        if mask.ndim == 2:
            # Resize mask to original image size if needed
            # PIL size is (width, height), numpy array shape is (height, width)
            expected_shape = (original_size[1], original_size[0])  # (height, width)
            if mask.shape != expected_shape:
                from PIL import Image as PILImage
                mask_img = PILImage.fromarray((mask > 0.5).astype(np.uint8) * 255, mode="L")
                mask_img = mask_img.resize(original_size, PILImage.NEAREST)
                mask_resized = np.array(mask_img)
            else:
                mask_resized = (mask > 0.5).astype(np.uint8) * 255
            
            # Create binary mask (True where mask is active)
            mask_binary = mask_resized > 127
            
            # Create new RGBA image with transparent background
            segment_array = img_array.copy()
            
            # Set alpha channel: 0 where mask is False, 255 where mask is True
            segment_array[:, :, 3] = np.where(mask_binary, 255, 0)
            
            # Optionally: set RGB to black where mask is False (for cleaner extraction)
            # Or keep original colors - keeping original colors looks better
            # segment_array[:, :, :3] = np.where(mask_binary[..., np.newaxis], segment_array[:, :, :3], 0)
            
            # Convert back to PIL Image
            segment_image = Image.fromarray(segment_array, mode='RGBA')
            
            # Increment instance count for this prompt
            instance_count += 1
            
            # Generate filename: {sanitized_prompt}_{instance_number}.png
            filename = f"{sanitized_prompt}_{instance_count}.png"
            
            # Determine full path
            if _is_network_path(output_path):
                normalized = output_path.replace('/', '\\')
                if not normalized.endswith('\\'):
                    normalized += '\\'
                filepath_str = os.path.join(normalized, filename).replace('/', '\\')
            else:
                if not output_path.endswith('/') and not output_path.endswith('\\'):
                    output_path += '/'
                filepath_str = os.path.join(output_path, filename)
            
            _ensure_directory_exists(filepath_str)
            
            # Save masked segment image
            segment_image.save(filepath_str, "PNG")
            saved_paths.append(filepath_str)
    
    return saved_paths


async def save_combined_mask_per_label(
    original_image: Image.Image,
    masks: torch.Tensor,
    labels: List[str],
    scores: torch.Tensor,
    grouped_detections: Dict[str, Dict[str, Any]],
    output_path: str,
    timestamp: Optional[int] = None
) -> Dict[str, str]:
    """
    Save combined mask images, one per unique label.
    Each image shows all instances of that label merged together.
    
    Args:
        original_image: Original PIL Image
        masks: Tensor of masks [N, H, W] or [1, N, H, W]
        labels: List of label names for each mask
        scores: Tensor of confidence scores
        grouped_detections: Dict mapping label to grouped detection info
        output_path: Directory path to save combined masks
        timestamp: Optional timestamp for filename (uses current time if None)
    
    Returns:
        Dict mapping label to file path of combined mask image
    """
    if timestamp is None:
        timestamp = int(time.time())
    
    if masks.numel() == 0:
        return {}
    
    masks_np = masks.cpu().numpy() if isinstance(masks, torch.Tensor) else masks
    if masks_np.ndim == 3 and masks_np.shape[0] == 1:
        masks_np = masks_np[0]
    elif masks_np.ndim == 4:
        masks_np = masks_np.squeeze(0)
    
    original_size = original_image.size
    
    if original_image.mode != 'RGBA':
        original_rgba = original_image.convert('RGBA')
    else:
        original_rgba = original_image.copy()
    
    img_array = np.array(original_rgba)
    
    saved_paths = {}
    
    label_colors = {
        "plant": (0, 255, 0),
        "soil": (139, 69, 19),
        "rock": (128, 128, 128),
        "water": (0, 0, 255),
        "person": (255, 0, 0),
        "car": (255, 255, 0),
    }
    
    default_colors = [
        (255, 0, 255),
        (0, 255, 255),
        (255, 128, 0),
        (128, 0, 255),
        (0, 128, 255),
        (255, 0, 128),
    ]
    
    unique_labels = list(grouped_detections.keys())
    
    for idx, label in enumerate(unique_labels):
        target_indices = [i for i, lbl in enumerate(labels) if lbl == label]
        
        if not target_indices:
            continue
        
        combined_array = np.zeros((original_size[1], original_size[0], 4), dtype=np.uint8)
        
        color = label_colors.get(label.lower(), default_colors[idx % len(default_colors)])
        rgb_color = color[:3] if len(color) > 3 else color
        
        for mask_idx in target_indices:
            if mask_idx < len(masks_np):
                mask = masks_np[mask_idx]
                if mask.ndim == 2:
                    expected_shape = (original_size[1], original_size[0])
                    if mask.shape != expected_shape:
                        mask_img = Image.fromarray((mask > 0.5).astype(np.uint8) * 255, mode="L")
                        mask_img = mask_img.resize(original_size, Image.NEAREST)
                        mask_resized = np.array(mask_img)
                    else:
                        mask_resized = (mask > 0.5).astype(np.uint8) * 255
                    
                    mask_binary = mask_resized > 127
                    combined_array[:, :, :3] = np.where(mask_binary[..., np.newaxis], rgb_color, combined_array[:, :, :3])
                    combined_array[:, :, 3] = np.where(mask_binary, 255, combined_array[:, :, 3])
        
        combined_image = Image.fromarray(combined_array, mode='RGBA')
        
        result_overlay = Image.alpha_composite(original_rgba, combined_image)
        
        info = grouped_detections.get(label, {})
        count = info.get("count", len(target_indices))
        conf_min = info.get("confidence_min", 0)
        conf_max = info.get("confidence_max", 0)
        area_ratio = info.get("total_mask_area_ratio", 0)
        
        result_rgb = result_overlay.convert("RGB")
        draw = ImageDraw.Draw(result_rgb)
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        except:
            font = ImageFont.load_default()
        
        if conf_min == conf_max:
            conf_str = f"{conf_min:.2f}"
        else:
            conf_str = f"{conf_min:.2f}-{conf_max:.2f}"
        
        label_text = f"{label} (n={count}, area={area_ratio}%, conf: {conf_str})"
        draw.text((10, 10), label_text, fill=(255, 255, 255), font=font)
        
        sanitized_label = _sanitize_filename(label)
        filename = f"{sanitized_label}_combined.png"
        
        if _is_network_path(output_path):
            normalized = output_path.replace('/', '\\')
            if not normalized.endswith('\\'):
                normalized += '\\'
            filepath_str = os.path.join(normalized, filename).replace('/', '\\')
        else:
            if not output_path.endswith('/') and not output_path.endswith('\\'):
                output_path += '/'
            filepath_str = os.path.join(output_path, filename)
        
        _ensure_directory_exists(filepath_str)
        result_rgb.save(filepath_str, "PNG")
        saved_paths[label] = filepath_str
    
    return saved_paths


async def save_all_combined_mask(
    original_image: Image.Image,
    masks: torch.Tensor,
    labels: List[str],
    scores: torch.Tensor,
    grouped_detections: Dict[str, Dict[str, Any]],
    output_path: str,
    timestamp: Optional[int] = None
) -> str:
    """
    Save single combined mask image with all labels visible, each in different color with legend.
    
    Args:
        original_image: Original PIL Image
        masks: Tensor of masks [N, H, W] or [1, N, H, W]
        labels: List of label names for each mask
        scores: Tensor of confidence scores
        grouped_detections: Dict mapping label to grouped detection info
        output_path: Directory path to save the combined image
        timestamp: Optional timestamp for filename (uses current time if None)
    
    Returns:
        Path to saved combined image
    """
    if timestamp is None:
        timestamp = int(time.time())
    
    if masks.numel() == 0:
        return None
    
    masks_np = masks.cpu().numpy() if isinstance(masks, torch.Tensor) else masks
    if masks_np.ndim == 3 and masks_np.shape[0] == 1:
        masks_np = masks_np[0]
    elif masks_np.ndim == 4:
        masks_np = masks_np.squeeze(0)
    
    original_size = original_image.size
    
    if original_image.mode != 'RGBA':
        original_rgba = original_image.convert('RGBA')
    else:
        original_rgba = original_image.copy()
    
    img_array = np.array(original_rgba)
    result_overlay = original_rgba.copy()
    
    unique_labels = list(grouped_detections.keys())
    
    label_colors = {
        "plant": (0, 255, 0, 128),
        "soil": (139, 69, 19, 128),
        "rock": (128, 128, 128, 128),
        "water": (0, 0, 255, 128),
        "person": (255, 0, 0, 128),
        "car": (255, 255, 0, 128),
    }
    
    default_colors = [
        (255, 0, 255, 128),
        (0, 255, 255, 128),
        (255, 128, 0, 128),
        (128, 0, 255, 128),
        (0, 128, 255, 128),
        (255, 0, 128, 128),
    ]
    
    for idx, label in enumerate(unique_labels):
        color = label_colors.get(label.lower(), default_colors[idx % len(default_colors)])
        target_indices = [i for i, lbl in enumerate(labels) if lbl == label]
        
        overlay = Image.new("RGBA", original_size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        
        for mask_idx in target_indices:
            if mask_idx < len(masks_np):
                mask = masks_np[mask_idx]
                if mask.ndim == 2:
                    expected_shape = (original_size[1], original_size[0])
                    if mask.shape != expected_shape:
                        mask_img = Image.fromarray((mask > 0.5).astype(np.uint8) * 255, mode="L")
                        mask_img = mask_img.resize(original_size, Image.NEAREST)
                        mask_resized = np.array(mask_img)
                    else:
                        mask_resized = (mask > 0.5).astype(np.uint8) * 255
                    
                    mask_binary = mask_resized > 127
                    mask_img = Image.fromarray(mask_binary.astype(np.uint8) * 255, mode="L")
                    overlay_draw.bitmap((0, 0), mask_img, fill=color)
        
        result_overlay = Image.alpha_composite(result_overlay, overlay)
    
    result_rgb = result_overlay.convert("RGB")
    draw = ImageDraw.Draw(result_rgb)
    
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    except:
        font = ImageFont.load_default()
        title_font = font
    
    legend_height = 25
    legend_padding = 10
    legend_line_height = 18
    legend_width = 220
    legend_entries = len(unique_labels)
    legend_box_height = legend_padding * 2 + legend_height + (legend_entries * legend_line_height)
    legend_box_width = legend_width
    
    legend_img = Image.new("RGBA", (legend_box_width, legend_box_height), (0, 0, 0, 180))
    legend_draw = ImageDraw.Draw(legend_img)
    
    legend_draw.text((legend_padding, legend_padding), "Detection Summary", fill=(255, 255, 255, 255), font=title_font)
    
    y_pos = legend_padding + legend_height
    for idx, label in enumerate(unique_labels):
        info = grouped_detections.get(label, {})
        count = info.get("count", 1)
        area_ratio = info.get("total_mask_area_ratio", 0)
        conf_min = info.get("confidence_min", 0)
        conf_max = info.get("confidence_max", 0)
        
        color = label_colors.get(label.lower(), default_colors[idx % len(default_colors)])
        rgb_color = (color[0], color[1], color[2])
        
        legend_draw.rectangle([legend_padding, y_pos - 2, legend_padding + 12, y_pos + 10], fill=rgb_color)
        
        if conf_min == conf_max:
            conf_str = f"{conf_min:.2f}"
        else:
            conf_str = f"{conf_min:.2f}-{conf_max:.2f}"
        
        text = f"{label} (n={count}, {area_ratio}%, {conf_str})"
        legend_draw.text((legend_padding + 18, y_pos), text, fill=(255, 255, 255, 255), font=font)
        y_pos += legend_line_height
    
    if result_rgb.mode != "RGBA":
        result_rgb = result_rgb.convert("RGBA")
    result_rgb = Image.alpha_composite(result_rgb, legend_img).convert("RGB")
    
    filename = "all_combined.png"
    
    if _is_network_path(output_path):
        normalized = output_path.replace('/', '\\')
        if not normalized.endswith('\\'):
            normalized += '\\'
        filepath_str = os.path.join(normalized, filename).replace('/', '\\')
    else:
        if not output_path.endswith('/') and not output_path.endswith('\\'):
            output_path += '/'
        filepath_str = os.path.join(output_path, filename)
    
    _ensure_directory_exists(filepath_str)
    result_rgb.save(filepath_str, "PNG")
    
    return filepath_str


def list_outputs() -> list:
    """List all output files."""
    if not OUTPUT_DIR.exists():
        return []
    
    files = []
    for filepath in OUTPUT_DIR.iterdir():
        if filepath.is_file():
            files.append({
                "name": filepath.name,
                "path": str(filepath),
                "size": filepath.stat().st_size,
                "modified": filepath.stat().st_mtime
            })
    
    return sorted(files, key=lambda x: x["modified"], reverse=True)
