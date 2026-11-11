"""
Visualization utilities for creating result images and metadata.
"""
import base64
import io
import torch
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from typing import List, Dict, Any, Optional, Tuple


def image_to_base64(image: Image.Image, format: str = "PNG") -> str:
    """Convert PIL Image to base64 string."""
    buffer = io.BytesIO()
    image.save(buffer, format=format)
    img_bytes = buffer.getvalue()
    return base64.b64encode(img_bytes).decode("utf-8")


def draw_corner_annotation(
    image: Image.Image,
    grouped_detections: Dict[str, Dict[str, Any]],
    position: str = "bottom-right",
    alpha: float = 0.7
) -> Image.Image:
    """Draw corner annotation with label/count/area/confidence info.
    
    Args:
        image: PIL Image to annotate
        grouped_detections: Dict mapping label to grouped detection info
                           (label, count, total_mask_area_ratio, confidence_min, confidence_max)
        position: Corner position - "top-left", "top-right", "bottom-left", "bottom-right"
        alpha: Transparency for annotation background
    
    Returns:
        Annotated PIL Image
    """
    result_img = image.convert("RGBA")
    draw = ImageDraw.Draw(result_img)
    
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 14)
    except:
        font = ImageFont.load_default()
        title_font = font
    
    lines = []
    for label, info in grouped_detections.items():
        count = info.get("count", 1)
        area_ratio = info.get("total_mask_area_ratio", 0)
        conf_min = info.get("confidence_min", 0)
        conf_max = info.get("confidence_max", 0)
        if conf_min == conf_max:
            conf_str = f"{conf_min:.2f}"
        else:
            conf_str = f"{conf_min:.2f}-{conf_max:.2f}"
        lines.append(f"{label} (n={count}, area={area_ratio}%, conf: {conf_str})")
    
    if not lines:
        return image.convert("RGB")
    
    padding = 10
    line_height = 20
    title_height = 25
    total_height = title_height + (len(lines) * line_height) + padding
    max_line_width = max(draw.textlength(line, font=font) for line in lines) if hasattr(draw, 'textlength') else max(len(line) * 8 for line in lines)
    max_title_width = draw.textlength("Detection Summary", font=title_font) if hasattr(draw, 'textlength') else len("Detection Summary") * 8
    box_width = int(max(max_line_width, max_title_width)) + (padding * 2)
    box_height = total_height + (padding * 2)
    
    img_width, img_height = result_img.size
    
    if position == "bottom-right":
        box_x = img_width - box_width - 10
        box_y = img_height - box_height - 10
    elif position == "top-right":
        box_x = img_width - box_width - 10
        box_y = 10
    elif position == "bottom-left":
        box_x = 10
        box_y = img_height - box_height - 10
    else:
        box_x = 10
        box_y = 10
    
    overlay = Image.new("RGBA", result_img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    
    bg_color = (0, 0, 0, int(255 * alpha))
    text_color = (255, 255, 255, 255)
    
    overlay_draw.rectangle([box_x, box_y, box_x + box_width, box_y + box_height], fill=bg_color)
    overlay_draw.text((box_x + padding, box_y + padding), "Detection Summary", fill=text_color, font=title_font)
    
    y_text = box_y + padding + title_height
    for line in lines:
        overlay_draw.text((box_x + padding, y_text), line, fill=text_color, font=font)
        y_text += line_height
    
    result_img = Image.alpha_composite(result_img, overlay)
    return result_img.convert("RGB")


def create_result_image(
    original_image: Image.Image,
    boxes: torch.Tensor,
    masks: torch.Tensor,
    scores: torch.Tensor,
    alpha: float = 0.5,
    labels: Optional[List[str]] = None,
    show_labels: bool = True,
    grouped_detections: Optional[Dict[str, Dict[str, Any]]] = None,
    corner_annotation_enabled: bool = False,
    corner_annotation_position: str = "bottom-right"
) -> Image.Image:
    """Create result image with overlays. Optional labels (one per box) shown beside confidence."""
    if isinstance(original_image, Image.Image):
        img_array = np.array(original_image)
    else:
        img_array = original_image
    
    result_img = Image.fromarray(img_array.copy())
    
    if masks.numel() > 0:
        masks_np = masks.cpu().numpy() if isinstance(masks, torch.Tensor) else masks
        if masks_np.ndim == 3:
            masks_np = masks_np[0] if masks_np.shape[0] == 1 else masks_np
        
        overlay = Image.new("RGBA", result_img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        
        colors = [
            (255, 0, 0, int(255 * alpha)),
            (0, 255, 0, int(255 * alpha)),
            (0, 0, 255, int(255 * alpha)),
            (255, 255, 0, int(255 * alpha)),
            (255, 0, 255, int(255 * alpha)),
            (0, 255, 255, int(255 * alpha)),
        ]
        
        for i, mask in enumerate(masks_np):
            if mask.ndim == 2:
                mask_binary = (mask > 0.5).astype(np.uint8) * 255
                mask_img = Image.fromarray(mask_binary, mode="L")
                color = colors[i % len(colors)]
                overlay_draw.bitmap((0, 0), mask_img, fill=color)
        
        result_img = Image.alpha_composite(result_img.convert("RGBA"), overlay).convert("RGB")
    
    if boxes.numel() > 0 and show_labels:
        draw = ImageDraw.Draw(result_img)
        boxes_np = boxes.cpu().numpy() if isinstance(boxes, torch.Tensor) else boxes
        scores_np = scores.cpu().numpy() if isinstance(scores, torch.Tensor) else scores
        
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
        except:
            font = ImageFont.load_default()
        
        for i, (box, score) in enumerate(zip(boxes_np, scores_np)):
            x0, y0, x1, y1 = box
            draw.rectangle([x0, y0, x1, y1], outline="red", width=2)
            if labels is not None and i < len(labels):
                label = f"{labels[i]} {score:.2f}"
            else:
                label = f"{score:.2f}"
            draw.text((x0, y0 - 20), label, fill="red", font=font)
    
    if corner_annotation_enabled and grouped_detections:
        result_img = draw_corner_annotation(
            result_img,
            grouped_detections,
            position=corner_annotation_position
        )
    
    return result_img


def create_label_combined_image(
    original_image: Image.Image,
    masks: torch.Tensor,
    labels: List[str],
    scores: torch.Tensor,
    target_label: str,
    grouped_detections: Dict[str, Dict[str, Any]],
    alpha: float = 0.5
) -> Image.Image:
    """Create combined image with all instances of a specific label merged.
    
    Args:
        original_image: Original PIL Image
        masks: Tensor of all masks [N, H, W] or [1, N, H, W]
        labels: List of label names for each mask
        scores: Tensor of confidence scores
        target_label: The label to combine
        grouped_detections: Dict mapping label to grouped detection info
        alpha: Transparency for mask overlay
    
    Returns:
        PIL Image with combined mask for target label
    """
    if isinstance(original_image, Image.Image):
        img_array = np.array(original_image)
    else:
        img_array = original_image
    
    result_img = Image.fromarray(img_array.copy())
    
    masks_np = masks.cpu().numpy() if isinstance(masks, torch.Tensor) else masks
    if masks_np.ndim == 3 and masks_np.shape[0] == 1:
        masks_np = masks_np[0]
    elif masks_np.ndim == 4:
        masks_np = masks_np.squeeze(0)
    
    scores_np = scores.cpu().numpy() if isinstance(scores, torch.Tensor) else scores
    
    target_indices = [i for i, lbl in enumerate(labels) if lbl == target_label]
    
    if not target_indices:
        return result_img
    
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
    label_idx = unique_labels.index(target_label) if target_label in unique_labels else 0
    color = label_colors.get(target_label.lower(), default_colors[label_idx % len(default_colors)])
    rgba_color = (*color, int(255 * alpha)) if len(color) == 3 else color
    
    overlay = Image.new("RGBA", result_img.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    
    for mask_idx in target_indices:
        if mask_idx < len(masks_np):
            mask = masks_np[mask_idx]
            if mask.ndim == 2:
                mask_binary = (mask > 0.5).astype(np.uint8) * 255
                mask_img = Image.fromarray(mask_binary, mode="L")
                overlay_draw.bitmap((0, 0), mask_img, fill=rgba_color)
    
    result_img = Image.alpha_composite(result_img.convert("RGBA"), overlay).convert("RGB")
    
    info = grouped_detections.get(target_label, {})
    conf_min = info.get("confidence_min", 0)
    conf_max = info.get("confidence_max", 0)
    area_ratio = info.get("total_mask_area_ratio", 0)
    
    result_rgb = result_img
    draw = ImageDraw.Draw(result_rgb)
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 16)
    except:
        font = ImageFont.load_default()
    
    count = len(target_indices)
    if conf_min == conf_max:
        conf_str = f"{conf_min:.2f}"
    else:
        conf_str = f"{conf_min:.2f}-{conf_max:.2f}"
    
    label_text = f"{target_label} (n={count}, area={area_ratio}%, conf: {conf_str})"
    draw.text((10, 10), label_text, fill="white", font=font)
    
    return result_rgb


def create_all_combined_image(
    original_image: Image.Image,
    masks: torch.Tensor,
    labels: List[str],
    scores: torch.Tensor,
    grouped_detections: Dict[str, Dict[str, Any]],
    alpha: float = 0.5
) -> Image.Image:
    """Create single image with all labels grouped, each label in a distinct color with legend.
    
    Args:
        original_image: Original PIL Image
        masks: Tensor of all masks [N, H, W] or [1, N, H, W]
        labels: List of label names for each mask
        scores: Tensor of confidence scores
        grouped_detections: Dict mapping label to grouped detection info
        alpha: Transparency for mask overlay
    
    Returns:
        PIL Image with all labels shown with different colors and legend
    """
    if isinstance(original_image, Image.Image):
        img_array = np.array(original_image)
    else:
        img_array = original_image
    
    result_img = Image.fromarray(img_array.copy())
    
    masks_np = masks.cpu().numpy() if isinstance(masks, torch.Tensor) else masks
    if masks_np.ndim == 3 and masks_np.shape[0] == 1:
        masks_np = masks_np[0]
    elif masks_np.ndim == 4:
        masks_np = masks_np.squeeze(0)
    
    unique_labels = list(grouped_detections.keys())
    
    label_colors = {
        "plant": (0, 255, 0, int(255 * alpha)),
        "soil": (139, 69, 19, int(255 * alpha)),
        "rock": (128, 128, 128, int(255 * alpha)),
        "water": (0, 0, 255, int(255 * alpha)),
        "person": (255, 0, 0, int(255 * alpha)),
        "car": (255, 255, 0, int(255 * alpha)),
    }
    
    default_colors = [
        (255, 0, 255, int(255 * alpha)),
        (0, 255, 255, int(255 * alpha)),
        (255, 128, 0, int(255 * alpha)),
        (128, 0, 255, int(255 * alpha)),
        (0, 128, 255, int(255 * alpha)),
        (255, 0, 128, int(255 * alpha)),
    ]
    
    for idx, label in enumerate(unique_labels):
        color = label_colors.get(label.lower(), default_colors[idx % len(default_colors)])
        target_indices = [i for i, lbl in enumerate(labels) if lbl == label]
        
        overlay = Image.new("RGBA", result_img.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        
        for mask_idx in target_indices:
            if mask_idx < len(masks_np):
                mask = masks_np[mask_idx]
                if mask.ndim == 2:
                    mask_binary = (mask > 0.5).astype(np.uint8) * 255
                    mask_img = Image.fromarray(mask_binary, mode="L")
                    overlay_draw.bitmap((0, 0), mask_img, fill=color)
        
        result_img = Image.alpha_composite(result_img.convert("RGBA"), overlay).convert("RGB")
    
    legend_height = 25
    legend_padding = 10
    legend_line_height = 20
    legend_width = 250
    legend_entries = len(unique_labels)
    legend_box_height = legend_padding * 2 + legend_height + (legend_entries * legend_line_height)
    
    legend_img = Image.new("RGBA", (legend_width, legend_box_height), (0, 0, 0, 180))
    legend_draw = ImageDraw.Draw(legend_img)
    
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 12)
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 12)
    except:
        font = ImageFont.load_default()
        title_font = font
    
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
        
        legend_draw.rectangle([legend_padding, y_pos - 3, legend_padding + 15, y_pos + 12], fill=rgb_color)
        
        if conf_min == conf_max:
            conf_str = f"{conf_min:.2f}"
        else:
            conf_str = f"{conf_min:.2f}-{conf_max:.2f}"
        
        text = f"{label} (n={count}, {area_ratio}%, {conf_str})"
        legend_draw.text((legend_padding + 20, y_pos), text, fill=(255, 255, 255, 255), font=font)
        y_pos += legend_line_height
    
    if result_img.mode != "RGBA":
        result_img = result_img.convert("RGBA")
    
    result_img = Image.alpha_composite(result_img, legend_img).convert("RGB")
    
    return result_img


def generate_metadata(
    original_image: Image.Image,
    text_prompt: str,
    boxes: torch.Tensor,
    masks: torch.Tensor,
    scores: torch.Tensor,
    device: str,
    confidence_threshold: float,
    model_resolution: int,
    inference_time: float,
    file_paths: Optional[Dict[str, Any]] = None,
    detection_labels: Optional[List[str]] = None,
    grouped_detections: Optional[Dict[str, Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """Generate LLM-friendly metadata."""
    num_detections = len(boxes) if boxes.numel() > 0 else 0
    width = original_image.size[0]
    height = original_image.size[1]
    area_pixels = width * height

    metadata = {
        "summary": f"Found {num_detections} object(s) matching '{text_prompt}' in the image.",
        "query": text_prompt,
        "detections": [],
        "image_info": {
            "width": width,
            "height": height,
            "area_pixels": area_pixels,
            "format": original_image.format or "RGB"
        },
        "model_info": {
            "device": device,
            "confidence_threshold": confidence_threshold,
            "resolution": model_resolution
        },
        "performance": {
            "inference_time_seconds": round(inference_time, 3),
            "num_detections": num_detections
        },
        "file_paths": file_paths or {
            "input_image": None,
            "overlay_image": None,
            "masked_segments": [],
            "combined_masks_per_label": {},
            "all_combined_mask": None
        }
    }

    if grouped_detections:
        metadata["grouped_detections"] = grouped_detections

    if num_detections > 0:
        boxes_np = boxes.cpu().numpy() if isinstance(boxes, torch.Tensor) else boxes
        scores_np = scores.cpu().numpy() if isinstance(scores, torch.Tensor) else scores
        masks_np = masks.cpu().numpy() if isinstance(masks, torch.Tensor) else masks
        if masks_np.ndim == 3 and masks_np.shape[0] == 1:
            masks_np = masks_np[0]

        for i, (box, score) in enumerate(zip(boxes_np, scores_np)):
            x0, y0, x1, y1 = box
            label = detection_labels[i] if detection_labels is not None and i < len(detection_labels) else text_prompt
            det_obj = {
                "id": i + 1,
                "label": label,
                "confidence": float(score),
                "bounding_box": {
                    "x_min": float(x0),
                    "y_min": float(y0),
                    "x_max": float(x1),
                    "y_max": float(y1),
                    "width": float(x1 - x0),
                    "height": float(y1 - y0)
                },
                "description": f"Object {i+1} ({label}) with {score:.1%} confidence"
            }
            if masks.numel() > 0:
                if masks_np.ndim == 3 and i < masks_np.shape[0]:
                    m = masks_np[i]
                elif masks_np.ndim == 2 and i == 0:
                    m = masks_np
                else:
                    m = None
                if m is not None:
                    mask_area = int((m > 0.5).sum())
                    det_obj["mask_area_pixels"] = mask_area
                    det_obj["mask_area_ratio"] = round(mask_area / area_pixels, 6)
            metadata["detections"].append(det_obj)
    else:
        metadata["message"] = f"No objects matching '{text_prompt}' were found above the confidence threshold ({confidence_threshold})."
    
    return metadata


def generate_text_description(metadata: dict) -> str:
    """
    Generate natural language description from metadata for LLM consumption.
    
    Args:
        metadata: Metadata dictionary from generate_metadata()
    
    Returns:
        Natural language text description of the segmentation results
    """
    query = metadata.get("query", "unknown")
    num_detections = metadata.get("performance", {}).get("num_detections", 0)
    image_info = metadata.get("image_info", {})
    width = image_info.get("width", 0)
    height = image_info.get("height", 0)
    inference_time = metadata.get("performance", {}).get("inference_time_seconds", 0)
    device = metadata.get("model_info", {}).get("device", "unknown")
    confidence_threshold = metadata.get("model_info", {}).get("confidence_threshold", 0.5)
    
    description_parts = []
    
    if num_detections > 0:
        description_parts.append(
            f"Found {num_detections} object(s) matching '{query}' in the image ({width}x{height} pixels)."
        )
        
        detections = metadata.get("detections", [])
        for detection in detections:
            obj_id = detection.get("id", 0)
            confidence = detection.get("confidence", 0.0)
            bbox = detection.get("bounding_box", {})
            x_min = bbox.get("x_min", 0)
            y_min = bbox.get("y_min", 0)
            x_max = bbox.get("x_max", 0)
            y_max = bbox.get("y_max", 0)
            bbox_width = bbox.get("width", 0)
            bbox_height = bbox.get("height", 0)
            
            description_parts.append(
                f"Object {obj_id}: confidence {confidence:.1%}, located at coordinates ({int(x_min)}, {int(y_min)}) to ({int(x_max)}, {int(y_max)}), size {int(bbox_width)}x{int(bbox_height)} pixels."
            )
    else:
        description_parts.append(
            f"No objects matching '{query}' were found above the confidence threshold ({confidence_threshold:.1%}) in the image ({width}x{height} pixels)."
        )
    
    description_parts.append(
        f"Processing time: {inference_time:.3f} seconds on {device.upper()} device."
    )
    
    return " ".join(description_parts)
