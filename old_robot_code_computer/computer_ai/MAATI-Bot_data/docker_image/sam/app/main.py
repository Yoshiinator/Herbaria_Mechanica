# =============================================================================
# main.py - SAM3 FastAPI Service
# =============================================================================
# Production-ready FastAPI service for Meta's Segment Anything Model 3 (SAM3).
# Supports automatic device detection: CUDA → MPS → CPU fallback.
# API-first design for n8n integration with LLM-friendly metadata.
# =============================================================================

import base64
import glob
import io
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import numpy as np
import torch
from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from PIL import Image
from pydantic import BaseModel, Field

from app.config import app_config, ModelConfig
from app.output_manager import (
    save_metadata,
    save_result_image,
    save_masked_segments,
    save_combined_mask_per_label,
    save_all_combined_mask,
)
from app.visualization import (
    create_result_image,
    generate_metadata,
    generate_text_description,
    image_to_base64,
    create_label_combined_image,
    create_all_combined_image,
)

# -----------------------------------------------------------------------------
# Logging Configuration
# -----------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper()),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# Path Validation Utility
# -----------------------------------------------------------------------------
def validate_file_path(
    file_path: str,
    allowed_base_paths: list[str],
    network_storage_enabled: bool = True,
    network_path_whitelist: Optional[list[str]] = None,
) -> str:
    """
    Validate and normalize file path for security.
    Prioritizes network paths (UNC format) for network-based systems.

    Args:
        file_path: Path to validate
        allowed_base_paths: List of allowed base directories (for local paths)
        network_storage_enabled: Whether to allow network paths (Windows UNC, etc.)
        network_path_whitelist: Optional list of allowed server/share combinations (e.g., ["\\\\nas-server\\share"])

    Returns:
        Normalized absolute path if valid

    Raises:
        HTTPException: If path is invalid or not allowed
    """
    import pathlib

    # Check for path traversal attempts
    if ".." in file_path or file_path.startswith("~"):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid path: Path traversal sequences (.., ~) are not allowed. Path: {file_path}",
        )

    # PRIORITY 1: Handle network paths (UNC format) - Windows: \\server\share or Linux: //server/share
    is_network_path = file_path.startswith("\\\\") or file_path.startswith("//")

    if is_network_path:
        if not network_storage_enabled:
            raise HTTPException(
                status_code=400,
                detail="Network storage paths are not enabled. Set NETWORK_STORAGE_ENABLED=true to enable.",
            )

        # Normalize network path - convert // to \\ for consistency
        if file_path.startswith("//"):
            # Linux format: convert //server/share to \\server\share for Windows compatibility
            normalized_path = "\\\\" + file_path[2:].replace("/", "\\")
        else:
            # Windows format: \\server\share
            normalized_path = os.path.normpath(file_path)

        # Optional: Check against network path whitelist for security
        if network_path_whitelist:
            path_allowed = False
            for allowed_network in network_path_whitelist:
                # Normalize whitelist entry
                normalized_allowed = allowed_network.replace("/", "\\")
                if normalized_path.lower().startswith(normalized_allowed.lower()):
                    path_allowed = True
                    break
            if not path_allowed:
                raise HTTPException(
                    status_code=403,
                    detail=f"Network path not allowed. Path must be within whitelisted network shares. Path: {file_path}",
                )

        # Check for path traversal in network path (even after normalization)
        if (
            ".." in normalized_path or normalized_path.count("\\") < 3
        ):  # \\server\share\path minimum
            raise HTTPException(
                status_code=400,
                detail=f"Invalid network path format. Expected: \\\\server\\share\\path\\file. Got: {file_path}",
            )

        # Check if file exists
        try:
            if not os.path.exists(normalized_path):
                raise HTTPException(
                    status_code=404, detail=f"File not found on network: {file_path}"
                )
            # Check if it's a file (not directory)
            if not os.path.isfile(normalized_path):
                raise HTTPException(
                    status_code=400, detail=f"Network path is not a file: {file_path}"
                )
            # Check file permissions (readable)
            if not os.access(normalized_path, os.R_OK):
                raise HTTPException(
                    status_code=403,
                    detail=f"File is not readable on network: {file_path}",
                )
        except OSError as e:
            raise HTTPException(
                status_code=500,
                detail=f"Error accessing network path {file_path}: {str(e)}",
            )

        return normalized_path

    # Handle local filesystem paths
    # For relative paths, try to resolve them relative to allowed base paths
    normalized_path = None
    if not os.path.isabs(file_path):
        # Relative path - try to resolve relative to each allowed base path
        for base_path in allowed_base_paths:
            base_abs = os.path.abspath(os.path.normpath(base_path))
            candidate_path = os.path.normpath(os.path.join(base_abs, file_path))
            # Check if candidate is still within base (prevents .. traversal)
            try:
                candidate_resolved = os.path.realpath(candidate_path)
                base_resolved = os.path.realpath(base_abs)
                if candidate_resolved.startswith(base_resolved):
                    if os.path.exists(candidate_path):
                        normalized_path = candidate_path
                        break
            except (OSError, ValueError):
                # If realpath fails, use string comparison
                if candidate_path.startswith(base_abs):
                    if os.path.exists(candidate_path):
                        normalized_path = candidate_path
                        break

        if normalized_path is None:
            # If no match found, try current working directory as fallback
            abs_path = os.path.abspath(file_path)
            normalized_path = os.path.normpath(abs_path)
    else:
        # Absolute path
        normalized_path = os.path.normpath(file_path)

    # Check if path is within allowed base directories
    path_allowed = False
    for base_path in allowed_base_paths:
        base_abs = os.path.abspath(os.path.normpath(base_path))
        try:
            # Check if normalized_path is within base_path
            normalized_path_resolved = os.path.realpath(normalized_path)
            base_path_resolved = os.path.realpath(base_abs)
            if normalized_path_resolved.startswith(base_path_resolved):
                path_allowed = True
                break
        except (OSError, ValueError):
            # If realpath fails (e.g., path doesn't exist yet), use string comparison
            if normalized_path.startswith(base_abs):
                path_allowed = True
                break

    if not path_allowed and allowed_base_paths:
        raise HTTPException(
            status_code=403,
            detail=f"Path not allowed. File paths must be within allowed base directories: {', '.join(allowed_base_paths)}. Path: {file_path}",
        )

    # Check if file exists
    if not os.path.exists(normalized_path):
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    # Check if it's a file (not directory)
    if not os.path.isfile(normalized_path):
        raise HTTPException(status_code=400, detail=f"Path is not a file: {file_path}")

    # Check file permissions (readable)
    if not os.access(normalized_path, os.R_OK):
        raise HTTPException(
            status_code=403, detail=f"File is not readable: {file_path}"
        )

    # Validate file extension (basic check)
    valid_extensions = {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".bmp",
        ".tiff",
        ".tif",
        ".webp",
    }
    file_ext = pathlib.Path(normalized_path).suffix.lower()
    if file_ext not in valid_extensions:
        logger.warning(
            f"File extension {file_ext} not in standard image extensions, but proceeding anyway"
        )

    return normalized_path


# -----------------------------------------------------------------------------
# BFloat16 Compatibility Patch (MUST be before SAM3 import)
# -----------------------------------------------------------------------------
# Check bfloat16 support once at startup
_BFLOAT16_SUPPORTED = False
try:
    if torch.cuda.is_available():
        test_tensor = torch.zeros(1, device="cuda", dtype=torch.bfloat16)
        _ = test_tensor + 1.0
        del test_tensor
        torch.cuda.empty_cache()
        _BFLOAT16_SUPPORTED = True
        logger.info("BFloat16 is supported on this GPU")
except (RuntimeError, TypeError, Exception) as e:
    _BFLOAT16_SUPPORTED = False
    logger.warning(
        f"BFloat16 is not supported on this GPU ({e}), will use float16/float32 instead"
    )

# Patch torch.autocast to handle bfloat16 compatibility issues
_original_autocast = torch.autocast


def _patched_autocast(device_type="cuda", dtype=None, enabled=True, **kwargs):
    """Patched autocast that automatically falls back from bfloat16 to float16 or float32."""
    if dtype == torch.bfloat16 and not _BFLOAT16_SUPPORTED:
        logger.warning("BFloat16 requested but not supported, using float16 instead")
        dtype = torch.float16

    if dtype == torch.bfloat16:
        try:
            if device_type == "cuda" and torch.cuda.is_available():
                test_tensor = torch.zeros(1, device="cuda", dtype=torch.bfloat16)
                _ = test_tensor + 1.0
                del test_tensor
                torch.cuda.empty_cache()
            return _original_autocast(
                device_type=device_type, dtype=dtype, enabled=enabled, **kwargs
            )
        except (RuntimeError, TypeError, Exception) as e:
            logger.warning(f"BFloat16 not supported ({e}), falling back to float16")
            try:
                if device_type == "cuda" and torch.cuda.is_available():
                    test_tensor = torch.zeros(1, device="cuda", dtype=torch.float16)
                    _ = test_tensor + 1.0
                    del test_tensor
                    torch.cuda.empty_cache()
                return _original_autocast(
                    device_type=device_type,
                    dtype=torch.float16,
                    enabled=enabled,
                    **kwargs,
                )
            except (RuntimeError, TypeError, Exception) as e2:
                logger.warning(f"Float16 not supported ({e2}), disabling autocast")
                return _original_autocast(
                    device_type=device_type,
                    dtype=torch.float32,
                    enabled=False,
                    **kwargs,
                )

    return _original_autocast(
        device_type=device_type, dtype=dtype, enabled=enabled, **kwargs
    )


torch.autocast = _patched_autocast

# Patch tensor.to() method to intercept bfloat16 conversions
_original_tensor_to = torch.Tensor.to


def _patched_tensor_to(self, *args, **kwargs):
    """Patch tensor.to() to prevent bfloat16 conversions if not supported."""
    if len(args) > 0 and args[0] == torch.bfloat16:
        if not _BFLOAT16_SUPPORTED:
            logger.warning(
                "BFloat16 conversion requested but not supported, using float16 instead"
            )
            new_args = (
                (torch.float16,) + args[1:] if len(args) > 1 else (torch.float16,)
            )
            return _original_tensor_to(self, *new_args, **kwargs)
        try:
            if self.device.type == "cuda" and torch.cuda.is_available():
                test_tensor = torch.zeros(1, device="cuda", dtype=torch.bfloat16)
                _ = test_tensor + 1.0
                del test_tensor
                torch.cuda.empty_cache()
            return _original_tensor_to(self, *args, **kwargs)
        except (RuntimeError, TypeError, Exception) as e:
            logger.warning(f"BFloat16 conversion not supported ({e}), using float16")
            new_args = (
                (torch.float16,) + args[1:] if len(args) > 1 else (torch.float16,)
            )
            try:
                return _original_tensor_to(self, *new_args, **kwargs)
            except (RuntimeError, TypeError, Exception):
                new_args = (
                    (torch.float32,) + args[1:] if len(args) > 1 else (torch.float32,)
                )
                return _original_tensor_to(self, *new_args, **kwargs)
    elif "dtype" in kwargs and kwargs["dtype"] == torch.bfloat16:
        if not _BFLOAT16_SUPPORTED:
            kwargs["dtype"] = torch.float16
            return _original_tensor_to(self, *args, **kwargs)
        try:
            if self.device.type == "cuda" and torch.cuda.is_available():
                test_tensor = torch.zeros(1, device="cuda", dtype=torch.bfloat16)
                _ = test_tensor + 1.0
                del test_tensor
                torch.cuda.empty_cache()
            return _original_tensor_to(self, *args, **kwargs)
        except (RuntimeError, TypeError, Exception) as e:
            logger.warning(f"BFloat16 conversion not supported ({e}), using float16")
            kwargs["dtype"] = torch.float16
            try:
                return _original_tensor_to(self, *args, **kwargs)
            except (RuntimeError, TypeError, Exception):
                kwargs["dtype"] = torch.float32
                return _original_tensor_to(self, *args, **kwargs)

    return _original_tensor_to(self, *args, **kwargs)


torch.Tensor.to = _patched_tensor_to
logger.info("Applied autocast and tensor.to() patches for BFloat16 compatibility")


# -----------------------------------------------------------------------------
# Device Detection
# -----------------------------------------------------------------------------
def get_optimal_device() -> str:
    """Detect the optimal compute device with graceful fallback."""
    env_device = os.getenv("DEVICE", "auto").lower()

    if env_device == "cuda":
        if torch.cuda.is_available():
            logger.info("CUDA device explicitly selected and available")
            return "cuda"
        else:
            logger.warning(
                "CUDA explicitly requested but not available, falling back to CPU"
            )
            return "cpu"
    elif env_device == "mps":
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            logger.info("MPS device explicitly selected and available")
            return "mps"
        else:
            logger.warning(
                "MPS explicitly requested but not available, falling back to CPU"
            )
            return "cpu"
    elif env_device == "cpu":
        logger.info("CPU device explicitly selected")
        return "cpu"

    # Auto-detection
    if torch.cuda.is_available():
        try:
            _ = torch.zeros(1).cuda()
            logger.info(f"CUDA detected: {torch.cuda.get_device_name(0)}")
            return "cuda"
        except Exception as e:
            logger.warning(f"CUDA available but not functional: {e}")

    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        try:
            _ = torch.zeros(1).to("mps")
            logger.info("MPS (Apple Silicon) detected and functional")
            return "mps"
        except Exception as e:
            logger.warning(f"MPS available but not functional: {e}")

    logger.info("Using CPU device (no GPU acceleration available)")
    return "cpu"


# -----------------------------------------------------------------------------
def _log_memory_usage(prefix: str = ""):
    """Log current GPU memory usage."""
    if torch.cuda.is_available():
        allocated = torch.cuda.memory_allocated() / 1e9
        reserved = torch.cuda.memory_reserved() / 1e9
        total = torch.cuda.get_device_properties(0).total_memory / 1e9
        logger.info(
            f"{prefix}GPU Memory: {allocated:.2f}GB / {total:.2f}GB (reserved: {reserved:.2f}GB)"
        )


def _cleanup_gpu_memory():
    """Force cleanup of GPU memory."""
    import gc

    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()


# -----------------------------------------------------------------------------
# Global State
# -----------------------------------------------------------------------------
class AppState:
    """Global application state holding the model and device info."""

    device: str = "cpu"
    model = None
    processor = None
    model_loaded: bool = False
    load_error: Optional[str] = None
    hf_token: Optional[str] = None


state = AppState()


# -----------------------------------------------------------------------------
# Model Cache Detection
# -----------------------------------------------------------------------------
def find_cached_model() -> Optional[str]:
    """Check if SAM3 model is already cached in HuggingFace cache."""
    hf_home = os.getenv("HF_HOME", "/models/huggingface")
    cache_dir = os.path.join(hf_home, "hub")

    model_cache_pattern = os.path.join(
        cache_dir, "models--facebook--sam3", "snapshots", "*", "sam3.pt"
    )

    cached_files = glob.glob(model_cache_pattern)
    if cached_files:
        checkpoint_path = cached_files[0]
        if os.path.exists(checkpoint_path) and os.path.getsize(checkpoint_path) > 0:
            logger.info(
                f"Found cached model at: {checkpoint_path} ({os.path.getsize(checkpoint_path) / 1e9:.2f} GB)"
            )
            return checkpoint_path
        else:
            logger.warning(
                f"Cached model file exists but is empty or invalid: {checkpoint_path}"
            )

    snapshots_dir = os.path.join(cache_dir, "models--facebook--sam3", "snapshots")
    blobs_dir = os.path.join(cache_dir, "models--facebook--sam3", "blobs")

    logger.info(f"Checking model cache directories:")
    logger.info(f"  HF_HOME: {hf_home}")
    logger.info(f"  cache_dir: {cache_dir}")
    logger.info(
        f"  model_base exists: {os.path.exists(os.path.join(cache_dir, 'models--facebook--sam3'))}"
    )
    logger.info(f"  snapshots_dir exists: {os.path.exists(snapshots_dir)}")
    logger.info(f"  blobs_dir exists: {os.path.exists(blobs_dir)}")

    if os.path.exists(snapshots_dir):
        try:
            snapshots = os.listdir(snapshots_dir)
            logger.info(f"  Snapshots found: {snapshots}")
            for snap in snapshots:
                snap_path = os.path.join(snapshots_dir, snap)
                if os.path.isdir(snap_path):
                    files = os.listdir(snap_path)
                    logger.info(f"    {snap}/ contents: {files[:10]}")
        except Exception as e:
            logger.warning(f"Could not list snapshots directory: {e}")

    if os.path.exists(blobs_dir):
        try:
            blobs = os.listdir(blobs_dir)
            logger.info(f"  Blobs found: {blobs}")
        except Exception as e:
            logger.warning(f"Could not list blobs directory: {e}")

    logger.info("No cached model found (or model incomplete)")
    return None


# -----------------------------------------------------------------------------
# Model Loading
# -----------------------------------------------------------------------------
def load_model():
    """Load the SAM3 model with proper device placement."""
    if state.model_loaded:
        return

    cached_checkpoint = find_cached_model()
    hf_token = state.hf_token or os.getenv("HF_TOKEN")

    if not cached_checkpoint and not hf_token:
        error_msg = (
            "HuggingFace authentication token is required to download the model.\n"
            "Please enter your HuggingFace token in the GUI or set HF_TOKEN environment variable.\n\n"
            "Setup steps:\n"
            "1. Create a HuggingFace account: https://huggingface.co/join\n"
            "2. Request access to the model: https://huggingface.co/facebook/sam3\n"
            "3. Generate an access token: https://huggingface.co/settings/tokens\n"
        )
        state.load_error = error_msg
        logger.error(error_msg)
        raise ValueError(error_msg)

    token_was_set = False
    if hf_token and not os.getenv("HF_TOKEN"):
        os.environ["HF_TOKEN"] = hf_token
        token_was_set = True
        token_preview = (
            f"{hf_token[:7]}...{hf_token[-4:]}" if len(hf_token) > 11 else "***"
        )
        logger.info(f"Using HuggingFace token from UI: {token_preview}")
    elif os.getenv("HF_TOKEN"):
        token_preview = (
            f"{os.getenv('HF_TOKEN')[:7]}...{os.getenv('HF_TOKEN')[-4:]}"
            if len(os.getenv("HF_TOKEN")) > 11
            else "***"
        )
        logger.info(f"Using HuggingFace token from environment: {token_preview}")

    try:
        logger.info(f"Loading SAM3 model on device: {state.device}")
        start_time = time.time()

        from sam3 import build_sam3_image_model
        from sam3.model.sam3_image_processor import Sam3Processor

        # Enable TF32 for CUDA
        if state.device == "cuda":
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            logger.info("TF32 enabled for GPU acceleration")

        config = app_config.get_config()

        if cached_checkpoint:
            logger.info(f"Loading model from cache: {cached_checkpoint}")
            state.model = build_sam3_image_model(
                device=state.device,
                eval_mode=True,
                checkpoint_path=cached_checkpoint,
                load_from_HF=False,
                enable_segmentation=True,
                enable_inst_interactivity=config.enable_instance_interactivity,
                compile=config.model_compilation,
            )
        else:
            logger.info("Downloading model from HuggingFace Hub...")
            state.model = build_sam3_image_model(
                device=state.device,
                eval_mode=True,
                load_from_HF=True,
                enable_segmentation=True,
                enable_inst_interactivity=config.enable_instance_interactivity,
                compile=config.model_compilation,
            )

        logger.info("Creating SAM3 processor...")
        state.processor = Sam3Processor(
            model=state.model,
            device=state.device,
            confidence_threshold=config.confidence_threshold,
        )
        logger.info("SAM3 processor created successfully")

        state.model_loaded = True
        load_time = time.time() - start_time
        logger.info(f"SAM3 model loaded successfully in {load_time:.2f}s")

        # Clear token from memory
        if state.hf_token:
            logger.info("Clearing HuggingFace token from memory (security)")
            state.hf_token = None

        if token_was_set:
            os.environ.pop("HF_TOKEN", None)

    except Exception as e:
        error_str = str(e)
        state.load_error = error_str

        if token_was_set:
            os.environ.pop("HF_TOKEN", None)

        if "401" in error_str or "Unauthorized" in error_str:
            helpful_msg = "HuggingFace Authentication Error. Please check your token and ensure you have access to the model."
            logger.error(helpful_msg)
        elif "404" in error_str or "Not Found" in error_str:
            helpful_msg = "Model Not Found Error. Please verify your access to https://huggingface.co/facebook/sam3"
            logger.error(helpful_msg)
        else:
            logger.error(f"Failed to load SAM3 model: {error_str}")

        raise


# -----------------------------------------------------------------------------
# Lifespan Context Manager
# -----------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info("=" * 60)
    logger.info("SAM3 FastAPI Service Starting")
    logger.info("=" * 60)

    state.device = get_optimal_device()
    logger.info(f"Selected device: {state.device}")

    logger.info(f"Python version: {sys.version}")
    logger.info(f"PyTorch version: {torch.__version__}")
    logger.info(f"CUDA available: {torch.cuda.is_available()}")
    if torch.cuda.is_available():
        logger.info(f"CUDA version: {torch.version.cuda}")
        logger.info(f"GPU: {torch.cuda.get_device_name(0)}")
        logger.info(
            f"GPU Memory: {torch.cuda.get_device_properties(0).total_memory / 1e9:.1f} GB"
        )

    logger.info("Service ready to accept requests")
    logger.info("=" * 60)

    yield

    logger.info("SAM3 FastAPI Service shutting down")
    if state.model is not None:
        del state.model
        del state.processor
        if state.device == "cuda":
            torch.cuda.empty_cache()


# -----------------------------------------------------------------------------
# FastAPI Application
# -----------------------------------------------------------------------------
app = FastAPI(
    title="SAM3 Segmentation API",
    description="Production API for Meta's Segment Anything Model 3 (SAM3) - n8n compatible",
    version="1.0.0",
    lifespan=lifespan,
)


# Middleware to catch encoding errors during request parsing
class EncodingErrorMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        logger.info(
            f"Middleware: {request.method} {request.url.path} (content-type: {request.headers.get('content-type', 'none')})"
        )
        try:
            response = await call_next(request)
            return response
        except UnicodeDecodeError as e:
            logger.error(f"UnicodeDecodeError in middleware: {e}")
            logger.error(f"Request path: {request.url.path}, Method: {request.method}")
            return JSONResponse(
                status_code=400,
                content={
                    "detail": "Invalid form data encoding. The image must be sent as a binary file field (not as text). Ensure in n8n that the 'image' field is set to type 'Binary File' or 'File', not 'String' or 'Text'.",
                    "error": "UnicodeDecodeError",
                    "message": "Binary data detected in text field. Please send image as binary file upload.",
                },
            )
        except Exception as e:
            # Check if the exception message contains encoding error
            error_str = str(e)
            if "utf-8" in error_str.lower() and "decode" in error_str.lower():
                logger.error(f"Encoding error detected: {e}")
                return JSONResponse(
                    status_code=400,
                    content={
                        "detail": "Invalid form data encoding. The image must be sent as a binary file field (not as text).",
                        "error": "EncodingError",
                        "message": "Binary data detected in text field. Please send image as binary file upload.",
                        "n8n_instructions": {
                            "problem": "n8n is sending binary image data in a text field instead of as a file upload.",
                            "solution": "In your n8n HTTP Request node, set the 'image' field type to 'Binary File' or 'File', not 'String' or 'Text'.",
                        },
                    },
                )
            raise


# Global Exception Handler for Encoding Errors
@app.exception_handler(UnicodeDecodeError)
async def unicode_decode_exception_handler(request: Request, exc: UnicodeDecodeError):
    """Handle UnicodeDecodeError that occurs during request parsing."""
    try:
        path = (
            getattr(request.url, "path", "unknown")
            if hasattr(request, "url") and request.url
            else "unknown"
        )
        method = getattr(request, "method", "unknown")
        logger.error(f"UnicodeDecodeError during request parsing: {exc}")
        logger.error(f"Request path: {path}, Method: {method}")
    except:
        logger.error(f"UnicodeDecodeError during request parsing: {exc}")
    return JSONResponse(
        status_code=400,
        content={
            "detail": "Invalid form data encoding. The image must be sent as a binary file field (not as text).",
            "error": "UnicodeDecodeError",
            "message": "Binary data detected in text field. Please send image as binary file upload.",
            "n8n_instructions": {
                "problem": "n8n is sending binary image data in a text field instead of as a file upload.",
                "solution": "In your n8n HTTP Request node:",
                "steps": [
                    "1. Set Body Content Type to 'Form-Data'",
                    "2. For the 'image' field:",
                    "   - Type must be 'Binary File' or 'File' (NOT 'String' or 'Text')",
                    "   - Value should come from the 'data' property of your Read Binary File node output",
                    "   - Use: {{ $json.binary.data }} or select 'Binary File' from the dropdown",
                    "3. For 'text_prompt' field: Type = 'String'",
                    "4. For other fields: Use appropriate types (Number, Boolean, etc.)",
                ],
                "example": "If Read Binary File outputs binary data in $json.binary.data, use that directly as a Binary File field, not as a String.",
            },
        },
    )


# Handler for RequestValidationError which might wrap encoding errors
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle RequestValidationError that might contain encoding errors."""
    error_str = str(exc)
    # Check if this is an encoding error
    if "utf-8" in error_str.lower() and "decode" in error_str.lower():
        logger.error(f"Encoding error in RequestValidationError: {exc}")
        return JSONResponse(
            status_code=400,
            content={
                "detail": "Invalid form data encoding. The image must be sent as a binary file field (not as text). Ensure in n8n that the 'image' field is set to type 'Binary File' or 'File', not 'String' or 'Text'.",
                "error": "EncodingError",
                "message": "Binary data detected in text field. Please send image as binary file upload.",
            },
        )
    # Re-raise for FastAPI's default handling
    from fastapi.exceptions import (
        RequestValidationError as FastAPIRequestValidationError,
    )
    from fastapi.exception_handlers import (
        http_exception_handler,
        request_validation_exception_handler,
    )

    return await request_validation_exception_handler(request, exc)


# Add middleware
app.add_middleware(EncodingErrorMiddleware)

# Static File Serving
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    # Mount static files with no-cache headers
    static_files = StaticFiles(directory=static_dir)
    app.mount("/gui/static", static_files, name="static")

    # Add no-cache headers for static files
    @app.middleware("http")
    async def add_no_cache_headers(request: StarletteRequest, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/gui/static/"):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


# -----------------------------------------------------------------------------
# Pydantic Models
# -----------------------------------------------------------------------------
class HealthResponse(BaseModel):
    """Health check response model."""

    status: str
    device: str
    torch_version: str
    cuda_available: bool
    cuda_version: Optional[str] = None
    gpu_name: Optional[str] = None
    gpu_memory_gb: Optional[float] = None
    model_loaded: bool
    model_downloaded: bool


class SetTokenRequest(BaseModel):
    """Request model for setting HuggingFace token."""

    token: str


class SetTokenResponse(BaseModel):
    """Response model for setting token."""

    success: bool
    message: str


class ModelStatusResponse(BaseModel):
    """Response model for model status check."""

    downloaded: bool
    path: Optional[str] = None
    model_loaded: bool = False
    load_error: Optional[str] = None
    device: Optional[str] = None


class SegmentRequestJSON(BaseModel):
    """JSON request model for base64 image input."""

    image_base64: str
    text_prompt: str
    confidence_threshold: Optional[float] = Field(None, ge=0, le=1)
    save_files: Optional[bool] = False
    output_basename: Optional[str] = Field(
        None,
        description="When save_files is True, save into a subfolder named {output_basename}_results (metadata, overlay, segments).",
    )
    output_folder: Optional[str] = Field(
        None,
        description="Output folder path to save results. If not set, uses RESULT_STORAGE_PATH from config.",
    )
    save_segments_separately: Optional[bool] = Field(
        None,
        description="When save_files is True, also save per-prompt segment images in the results folder.",
    )


class SegmentResponse(BaseModel):
    """Segmentation response with JSON metadata and file paths."""

    success: bool
    device_used: str
    inference_time_ms: float
    result_image_base64: str
    result_image_format: str
    metadata: dict
    optional_files: Optional[dict] = None


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------
@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Health check endpoint."""
    cached_model = find_cached_model()
    response = {
        "status": "healthy",
        "device": state.device,
        "torch_version": torch.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda if torch.cuda.is_available() else None,
        "gpu_name": torch.cuda.get_device_name(0)
        if torch.cuda.is_available()
        else None,
        "gpu_memory_gb": (
            round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)
            if torch.cuda.is_available()
            else None
        ),
        "model_loaded": state.model_loaded,
        "model_downloaded": cached_model is not None,
    }

    if state.load_error:
        response["status"] = "degraded"
        response["error"] = state.load_error

    return HealthResponse(**response)


@app.post("/api/set-token", response_model=SetTokenResponse, tags=["Authentication"])
async def set_token(request: SetTokenRequest):
    """Set HuggingFace authentication token for model download."""
    if not request.token or not request.token.strip():
        raise HTTPException(status_code=400, detail="Token cannot be empty")

    state.hf_token = request.token.strip()
    state.load_error = None

    logger.info("HuggingFace token received from UI")

    return SetTokenResponse(
        success=True,
        message="Token set successfully. Model will be downloaded on first use.",
    )


@app.post("/api/download-model", tags=["Model"])
async def download_model_endpoint():
    """Trigger immediate model download using the stored token."""
    logger.info("=" * 60)
    logger.info("Download model endpoint called")
    logger.info(
        f"Current state: model_loaded={state.model_loaded}, hf_token_set={state.hf_token is not None}"
    )

    cached_checkpoint = find_cached_model()
    logger.info(f"Cached checkpoint found: {cached_checkpoint}")

    if cached_checkpoint and state.model_loaded:
        return {
            "success": True,
            "message": "Model is already downloaded and loaded.",
            "model_loaded": True,
            "cached_path": cached_checkpoint,
        }

    if not state.hf_token and not os.getenv("HF_TOKEN"):
        logger.error("No HuggingFace token available")
        raise HTTPException(
            status_code=400,
            detail="No HuggingFace token available. Please set token first using /api/set-token",
        )

    try:
        logger.info("Starting model load/download...")
        load_model()
        logger.info(f"Model load completed. model_loaded={state.model_loaded}")
        return {
            "success": True,
            "message": "Model downloaded and loaded successfully!",
            "model_loaded": state.model_loaded,
        }
    except Exception as e:
        error_str = str(e)
        state.load_error = error_str
        logger.error(f"Model download failed: {error_str}", exc_info=True)

        if "401" in error_str or "Unauthorized" in error_str:
            detail = "Authentication failed. Please check your HuggingFace token."
        elif "404" in error_str or "Not Found" in error_str:
            detail = "Model not found. Please verify your access to https://huggingface.co/facebook/sam3"
        else:
            detail = f"Model download failed: {error_str}"

        raise HTTPException(status_code=500, detail=detail)


@app.get("/api/model-status", response_model=ModelStatusResponse, tags=["Model"])
async def get_model_status():
    """Check if SAM3 model is downloaded and cached."""
    cached_model = find_cached_model()
    return ModelStatusResponse(
        downloaded=cached_model is not None,
        path=cached_model,
        model_loaded=state.model_loaded,
        load_error=state.load_error,
        device=state.device,
    )


@app.get("/api/debug-model", tags=["Debug"])
async def debug_model():
    """Debug endpoint to check detailed model status."""
    cached_model = find_cached_model()

    import os

    hf_home = os.getenv("HF_HOME", "/models/huggingface")
    cache_dir = os.path.join(hf_home, "hub")
    model_base = os.path.join(cache_dir, "models--facebook--sam3")

    debug_info = {
        "state.model_loaded": state.model_loaded,
        "state.load_error": state.load_error,
        "state.device": state.device,
        "state.model": "loaded" if state.model is not None else None,
        "state.processor": "loaded" if state.processor is not None else None,
        "cached_checkpoint": cached_model,
        "hf_home": hf_home,
        "cache_dir": cache_dir,
        "model_base_exists": os.path.exists(model_base),
        "snapshots_dir": os.path.join(model_base, "snapshots")
        if os.path.exists(model_base)
        else None,
        "env_hf_token_set": os.getenv("HF_TOKEN") is not None,
        "state_hf_token_set": state.hf_token is not None,
    }

    if os.path.exists(os.path.join(model_base, "snapshots")):
        snapshots_path = os.path.join(model_base, "snapshots")
        debug_info["snapshots_contents"] = (
            os.listdir(snapshots_path) if os.path.exists(snapshots_path) else []
        )
        for snapshot in os.listdir(snapshots_path):
            snapshot_path = os.path.join(snapshots_path, snapshot)
            if os.path.isdir(snapshot_path):
                files = os.listdir(snapshot_path)
                debug_info[f"sam3.pt_in_{snapshot}"] = "sam3.pt" in files
                debug_info[f"files_in_{snapshot}"] = files[:5]

    return debug_info


@app.post("/api/segment", response_model=SegmentResponse, tags=["Segmentation"])
async def segment_image(
    file_path: str = Form(
        ..., description="Path to image file (local filesystem or network storage)"
    ),
    text_prompt: str = Form(...),
    output_folder: Optional[str] = Form(
        None, description="Output folder path (defaults to RESULT_STORAGE_PATH)"
    ),
    save_segments_separately: Optional[str] = Form(
        None,
        description="Save individual masks and cropped objects (string 'true'/'false' from FormData)",
    ),
    save_combined_mask_per_label: Optional[str] = Form(
        None,
        description="Save combined mask per label (string 'true'/'false' from FormData)",
    ),
    save_all_combined_mask: Optional[str] = Form(
        None, description="Save all combined mask (string 'true'/'false' from FormData)"
    ),
    show_bounding_box_labels: Optional[str] = Form(
        None,
        description="Show bounding box labels (string 'true'/'false' from FormData)",
    ),
    corner_annotation_enabled: Optional[str] = Form(
        None, description="Show corner annotation (string 'true'/'false' from FormData)"
    ),
    confidence_threshold: Optional[float] = Form(
        None, ge=0, le=1, description="Confidence threshold override"
    ),
    image_resolution: Optional[int] = Form(
        None, ge=224, le=2048, description="Image resolution override"
    ),
    enable_instance_interactivity: Optional[bool] = Form(
        None, description="Enable instance interactivity override"
    ),
    model_compilation: Optional[bool] = Form(
        None, description="Enable model compilation override"
    ),
):
    """Segment objects in an image using text prompts (simplified JSON response).

    Accepts file paths for input and returns JSON metadata with file paths for all saved outputs.

    **Parameters:**
    - file_path: Path to input image (required)
    - text_prompt: Text prompt describing objects to segment (required)
    - output_folder: Output folder path (optional, defaults to RESULT_STORAGE_PATH)
    - save_segments_separately: Save individual masks and cropped objects (optional, default: false)
    - confidence_threshold: Override confidence threshold (optional, 0-1)
    - image_resolution: Override image resolution (optional, 224-2048)
    - enable_instance_interactivity: Override instance interactivity setting (optional)
    - model_compilation: Override model compilation setting (optional)

    **Response:**
    Always returns JSON with:
    - result_image_base64: Base64-encoded overlay image
    - metadata: Full metadata including file_paths dictionary with:
      - input_image: Path to input image
      - overlay_image: Path to saved overlay image
      - individual_masks: List of paths to individual mask images (if saved)
      - cropped_objects: List of paths to cropped object images (if saved)

    **Path Examples:**
    - Shared volume: `/home/node/.n8n-files/input/photo.jpg`
    - Network: `\\\\nas-server\\images\\photo.jpg`
    - Local: `/data/images/photo.jpg`
    """
    start_time = time.time()

    if not state.model_loaded:
        cached_checkpoint = find_cached_model()
        if cached_checkpoint:
            try:
                load_model()
            except Exception as e:
                raise HTTPException(
                    status_code=503, detail=f"Model failed to load: {e}"
                )
        else:
            raise HTTPException(
                status_code=503,
                detail="Model not loaded. Please download the model first using /api/download-model.",
            )

    config = app_config.get_config()

    # Apply configuration overrides
    threshold = (
        confidence_threshold
        if confidence_threshold is not None
        else config.confidence_threshold
    )
    if confidence_threshold is not None:
        state.processor.confidence_threshold = threshold

    # Handle image resolution override (requires processor update)
    if image_resolution is not None:
        # Note: Changing resolution requires recreating processor, which is complex
        # For now, log a warning and use current resolution
        logger.warning(
            f"Image resolution override requested ({image_resolution}), but dynamic resolution change not yet implemented. Using current resolution: {config.image_resolution}"
        )

    # Determine output folder
    output_dir = output_folder if output_folder else config.result_storage_path
    if not output_dir:
        output_dir = "/outputs"  # Fallback to default

    # Validate output folder if provided
    if output_folder:
        # Validate against allowed base paths
        try:
            validated_output = validate_file_path(
                file_path=output_folder
                if os.path.isdir(output_folder)
                or output_folder.endswith("/")
                or output_folder.endswith("\\")
                else os.path.dirname(output_folder),
                allowed_base_paths=config.allowed_base_paths,
                network_storage_enabled=config.network_storage_enabled,
                network_path_whitelist=config.network_path_whitelist,
            )
            output_dir = (
                validated_output
                if os.path.isdir(validated_output)
                else os.path.dirname(validated_output)
            )
        except HTTPException:
            # If validation fails, try to use as-is (might be a new directory to create)
            output_dir = output_folder

    try:
        _cleanup_gpu_memory()
        _log_memory_usage("Pre-request: ")

        # Validate and normalize file path
        validated_path = validate_file_path(
            file_path=file_path,
            allowed_base_paths=config.allowed_base_paths,
            network_storage_enabled=config.network_storage_enabled,
            network_path_whitelist=config.network_path_whitelist,
        )

        logger.info(f"Processing image from path: {validated_path}")

        # Per-run output folder: {original_filename}_results
        original_basename = Path(validated_path).stem
        run_output_dir = os.path.join(output_dir, f"{original_basename}_results")
        Path(run_output_dir).mkdir(parents=True, exist_ok=True)

        # Read file from filesystem
        try:
            with open(validated_path, "rb") as f:
                contents = f.read()
        except PermissionError:
            raise HTTPException(
                status_code=403,
                detail=f"Permission denied: Cannot read file {file_path}",
            )
        except OSError as e:
            raise HTTPException(
                status_code=500, detail=f"Error reading file {file_path}: {str(e)}"
            )

        # Validate file is not empty
        if not contents or len(contents) == 0:
            raise HTTPException(status_code=400, detail="File is empty")

        # Validate file size (max 50MB)
        if len(contents) > 50 * 1024 * 1024:
            raise HTTPException(
                status_code=400, detail="File size exceeds maximum limit of 50MB"
            )

        # Validate image file signature (magic bytes)
        # PNG: 0x89 0x50 0x4E 0x47
        # JPEG: 0xFF 0xD8
        # GIF: 0x47 0x49 0x46
        # BMP: 0x42 0x4D
        is_valid_image = False
        if len(contents) >= 4:
            if contents[:4] == b"\x89PNG":  # PNG
                is_valid_image = True
            elif contents[:2] == b"\xff\xd8":  # JPEG
                is_valid_image = True
            elif contents[:3] == b"GIF":  # GIF
                is_valid_image = True
            elif contents[:2] == b"BM":  # BMP
                is_valid_image = True

        if not is_valid_image:
            logger.warning(
                f"File does not appear to be a valid image. First bytes: {contents[:8].hex() if len(contents) >= 8 else 'too short'}"
            )
            # Still try to open with PIL, as it can handle more formats

        # Open and validate image with PIL
        try:
            pil_image = Image.open(io.BytesIO(contents)).convert("RGB")
            logger.info(
                f"Processing image: {pil_image.size[0]}x{pil_image.size[1]}, format: {pil_image.format}"
            )
        except Exception as img_error:
            logger.error(f"Failed to open image: {img_error}")
            raise HTTPException(
                status_code=400,
                detail=f"Invalid image file. Please ensure the file is a valid image format (PNG, JPEG, GIF, BMP). Error: {str(img_error)}",
            )

        # Parse multiple prompts (comma-separated); treat as single prompt if no commas
        prompts = [p.strip() for p in text_prompt.split(",") if p.strip()] or [
            text_prompt
        ]

        # Run inference: set image once, then one inference per prompt; merge results with labels
        with torch.inference_mode():
            inference_state = state.processor.set_image(pil_image)
            all_boxes, all_masks, all_scores, all_labels = [], [], [], []
            per_prompt_masks = []  # (masks_tensor, prompt_str) for segment saving per prompt

            for prompt in prompts:
                inference_state = state.processor.set_text_prompt(
                    state=inference_state,
                    prompt=prompt,
                )
                if "boxes" in inference_state and len(inference_state["boxes"]) > 0:
                    b = inference_state["boxes"]
                    m = (
                        inference_state["masks"].squeeze(1)
                        if inference_state["masks"].dim() > 2
                        else inference_state["masks"]
                    )
                    s = inference_state["scores"]
                    all_boxes.append(b)
                    all_masks.append(m)
                    all_scores.append(s)
                    all_labels.extend([prompt] * len(b))
                    per_prompt_masks.append((m, prompt))

            if all_boxes:
                boxes = torch.cat(all_boxes, dim=0)
                masks = torch.cat(all_masks, dim=0)
                scores = torch.cat(all_scores, dim=0)
                labels = all_labels
            else:
                boxes = torch.tensor([])
                masks = torch.tensor([])
                scores = torch.tensor([])
                labels = []

        # Prepare file paths dictionary
        file_paths = {
            "input_image": file_path,
            "overlay_image": None,
            "masked_segments": [],
            "combined_masks_per_label": {},
            "all_combined_mask": None,
        }

        timestamp = int(time.time())

        # Parse all options upfront
        save_segments = False
        if save_segments_separately is not None:
            if isinstance(save_segments_separately, str):
                save_segments = save_segments_separately.lower() in (
                    "true",
                    "1",
                    "yes",
                    "on",
                )
            elif isinstance(save_segments_separately, bool):
                save_segments = save_segments_separately
        else:
            save_segments = config.save_segments_separately

        save_combined_per_label = False
        if save_combined_mask_per_label is not None:
            if isinstance(save_combined_mask_per_label, str):
                save_combined_per_label = save_combined_mask_per_label.lower() in (
                    "true",
                    "1",
                    "yes",
                    "on",
                )
            elif isinstance(save_combined_mask_per_label, bool):
                save_combined_per_label = save_combined_mask_per_label
        else:
            save_combined_per_label = config.save_combined_mask_per_label

        save_all_combined = False
        if save_all_combined_mask is not None:
            if isinstance(save_all_combined_mask, str):
                save_all_combined = save_all_combined_mask.lower() in (
                    "true",
                    "1",
                    "yes",
                    "on",
                )
            elif isinstance(save_all_combined_mask, bool):
                save_all_combined = save_all_combined_mask
        else:
            save_all_combined = config.save_all_combined_mask

        show_labels = True
        if show_bounding_box_labels is not None:
            if isinstance(show_bounding_box_labels, str):
                show_labels = show_bounding_box_labels.lower() in (
                    "true",
                    "1",
                    "yes",
                    "on",
                )
            elif isinstance(show_bounding_box_labels, bool):
                show_labels = show_bounding_box_labels
        else:
            show_labels = config.show_bounding_box_labels

        corner_annotation = False
        if corner_annotation_enabled is not None:
            if isinstance(corner_annotation_enabled, str):
                corner_annotation = corner_annotation_enabled.lower() in (
                    "true",
                    "1",
                    "yes",
                    "on",
                )
            elif isinstance(corner_annotation_enabled, bool):
                corner_annotation = corner_annotation_enabled
        else:
            corner_annotation = config.corner_annotation_enabled

        corner_position = config.corner_annotation_position

        # Build grouped detections info
        grouped_detections = {}
        if labels and boxes.numel() > 0:
            image_area = pil_image.size[0] * pil_image.size[1]
            masks_np = masks.cpu().numpy() if isinstance(masks, torch.Tensor) else masks
            if masks_np.ndim == 3 and masks_np.shape[0] == 1:
                masks_np = masks_np[0]
            elif masks_np.ndim == 4:
                masks_np = masks_np.squeeze(0)

            for i, label in enumerate(labels):
                if label not in grouped_detections:
                    grouped_detections[label] = {
                        "label": label,
                        "count": 0,
                        "confidence_min": 1.0,
                        "confidence_max": 0.0,
                        "total_mask_area_pixels": 0,
                        "detection_ids": [],
                    }
                grouped_detections[label]["count"] += 1
                score_val = (
                    scores[i].item() if hasattr(scores[i], "item") else scores[i]
                )
                grouped_detections[label]["confidence_min"] = min(
                    grouped_detections[label]["confidence_min"], score_val
                )
                grouped_detections[label]["confidence_max"] = max(
                    grouped_detections[label]["confidence_max"], score_val
                )
                grouped_detections[label]["detection_ids"].append(i + 1)

                if i < len(masks_np):
                    m = masks_np[i]
                    if m is not None and m.ndim == 2:
                        mask_area = int((m > 0.5).sum())
                        grouped_detections[label]["total_mask_area_pixels"] += mask_area

            for label in grouped_detections:
                area_pixels = grouped_detections[label]["total_mask_area_pixels"]
                grouped_detections[label]["total_mask_area_ratio"] = round(
                    area_pixels / image_area * 100, 2
                )

        if boxes.numel() > 0:
            masks_for_viz = masks.squeeze(1) if masks.dim() > 2 else masks
            result_image = create_result_image(
                original_image=pil_image,
                boxes=boxes,
                masks=masks_for_viz,
                scores=scores,
                labels=labels,
                show_labels=show_labels,
                grouped_detections=grouped_detections if corner_annotation else None,
                corner_annotation_enabled=corner_annotation,
                corner_annotation_position=corner_position,
            )

            result_base64 = image_to_base64(result_image)

            inference_time = time.time() - start_time

            # Save overlay image
            result_bytes = base64.b64decode(result_base64)
            overlay_path = await save_result_image(result_bytes, run_output_dir)
            file_paths["overlay_image"] = overlay_path

            if save_segments and per_prompt_masks:
                for masks_for_prompt, prompt in per_prompt_masks:
                    segment_paths = await save_masked_segments(
                        masks=masks_for_prompt,
                        original_image=pil_image,
                        text_prompt=prompt,
                        output_path=run_output_dir,
                        timestamp=timestamp,
                    )
                    file_paths["masked_segments"].extend(segment_paths)

            # Save combined masks per label (one image per unique label with all instances merged)
            if save_combined_per_label and grouped_detections:
                combined_paths = await save_combined_mask_per_label(
                    original_image=pil_image,
                    masks=masks_for_viz,
                    labels=labels,
                    scores=scores,
                    grouped_detections=grouped_detections,
                    output_path=run_output_dir,
                    timestamp=timestamp,
                )
                file_paths["combined_masks_per_label"] = combined_paths

            # Save all combined mask (only if more than 1 unique label - otherwise it's same as per-label combined)
            num_unique_labels = len(grouped_detections)
            if save_all_combined and grouped_detections and num_unique_labels > 1:
                all_combined_path = await save_all_combined_mask(
                    original_image=pil_image,
                    masks=masks_for_viz,
                    labels=labels,
                    scores=scores,
                    grouped_detections=grouped_detections,
                    output_path=run_output_dir,
                    timestamp=timestamp,
                )
                file_paths["all_combined_mask"] = all_combined_path

            metadata = generate_metadata(
                original_image=pil_image,
                text_prompt=text_prompt,
                boxes=boxes,
                masks=masks_for_viz,
                scores=scores,
                device=state.device,
                confidence_threshold=threshold,
                model_resolution=config.image_resolution,
                inference_time=inference_time,
                file_paths=file_paths,
                detection_labels=labels,
                grouped_detections=grouped_detections,
            )

            # Save metadata (filename includes original image name)
            metadata_path = await save_metadata(
                metadata, run_output_dir, original_filename=original_basename
            )

            inference_time_ms = (time.time() - start_time) * 1000
            logger.info(
                f"Segmentation complete: {len(boxes)} objects in {inference_time_ms:.1f}ms"
            )

            return SegmentResponse(
                success=True,
                device_used=state.device,
                inference_time_ms=round(inference_time_ms, 2),
                result_image_base64=result_base64,
                result_image_format="png",
                metadata=metadata,
                optional_files={
                    "result_image_path": overlay_path,
                    "metadata_path": metadata_path,
                },
            )
        else:
            inference_time = time.time() - start_time

            # Save original image as result (no detections)
            result_base64 = image_to_base64(pil_image)
            result_bytes = base64.b64decode(result_base64)
            overlay_path = await save_result_image(result_bytes, run_output_dir)
            file_paths["overlay_image"] = overlay_path

            metadata = generate_metadata(
                original_image=pil_image,
                text_prompt=text_prompt,
                boxes=torch.tensor([]),
                masks=torch.tensor([]),
                scores=torch.tensor([]),
                device=state.device,
                confidence_threshold=threshold,
                model_resolution=config.image_resolution,
                inference_time=inference_time,
                file_paths=file_paths,
            )

            # Save metadata (filename includes original image name)
            metadata_path = await save_metadata(
                metadata, run_output_dir, original_filename=original_basename
            )

            inference_time_ms = (time.time() - start_time) * 1000

            return SegmentResponse(
                success=True,
                device_used=state.device,
                inference_time_ms=round(inference_time_ms, 2),
                result_image_base64=result_base64,
                result_image_format="png",
                metadata=metadata,
                optional_files={
                    "result_image_path": overlay_path,
                    "metadata_path": metadata_path,
                },
            )
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        logger.error(f"Segmentation failed: {e}", exc_info=True)
        error_detail = str(e)
        # Provide more helpful error messages for common issues
        if "cannot identify image file" in error_detail.lower():
            error_detail = "Invalid image file format. Please ensure the file is a valid image (PNG, JPEG, GIF, BMP)."
        elif "CUDA error" in error_detail or "out of memory" in error_detail.lower():
            _cleanup_gpu_memory()
            _log_memory_usage("Post-OOM cleanup: ")
            error_detail = (
                f"GPU memory exhausted. Tips:\n"
                f"1. Use fewer segmentation terms\n"
                f"2. Reduce image size\n"
                f"3. Call /api/cleanup-gpu before processing"
            )
        raise HTTPException(status_code=500, detail=error_detail)
    finally:
        _cleanup_gpu_memory()
        _log_memory_usage("Post-request: ")


@app.post("/api/segment/json", response_model=SegmentResponse, tags=["Segmentation"])
async def segment_image_json(request: SegmentRequestJSON):
    """Segment objects using JSON request with base64 image (DEPRECATED - use /api/segment with file_path instead).

    This endpoint is kept for backward compatibility but is deprecated.
    Use /api/segment with file_path instead for better performance.
    """
    start_time = time.time()

    if not state.model_loaded:
        cached_checkpoint = find_cached_model()
        if cached_checkpoint:
            try:
                load_model()
            except Exception as e:
                raise HTTPException(
                    status_code=503, detail=f"Model failed to load: {e}"
                )
        else:
            raise HTTPException(
                status_code=503,
                detail="Model not loaded. Please download the model first using /api/download-model.",
            )

    config = app_config.get_config()
    threshold = (
        request.confidence_threshold
        if request.confidence_threshold is not None
        else config.confidence_threshold
    )

    if request.confidence_threshold is not None:
        state.processor.confidence_threshold = threshold

    try:
        image_bytes = base64.b64decode(request.image_base64)
        pil_image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        logger.info(f"Processing image: {pil_image.size[0]}x{pil_image.size[1]}")

        # Parse multiple prompts (comma-separated), same as file-path endpoint
        prompts = [p.strip() for p in request.text_prompt.split(",") if p.strip()] or [
            request.text_prompt
        ]

        with torch.inference_mode():
            inference_state = state.processor.set_image(pil_image)
            all_boxes, all_masks, all_scores, all_labels = [], [], [], []
            per_prompt_masks = []
            for prompt in prompts:
                inference_state = state.processor.set_text_prompt(
                    state=inference_state,
                    prompt=prompt,
                )
                if "boxes" in inference_state and len(inference_state["boxes"]) > 0:
                    b = inference_state["boxes"]
                    m = (
                        inference_state["masks"].squeeze(1)
                        if inference_state["masks"].dim() > 2
                        else inference_state["masks"]
                    )
                    s = inference_state["scores"]
                    all_boxes.append(b)
                    all_masks.append(m)
                    all_scores.append(s)
                    all_labels.extend([prompt] * len(b))
                    per_prompt_masks.append((m, prompt))
            if all_boxes:
                boxes = torch.cat(all_boxes, dim=0)
                masks = torch.cat(all_masks, dim=0)
                scores = torch.cat(all_scores, dim=0)
                labels = all_labels
            else:
                boxes = torch.tensor([])
                masks = torch.tensor([])
                scores = torch.tensor([])
                labels = []

        output_dir = request.output_folder if request.output_folder else (config.result_storage_path or "/outputs")
        run_output_dir = None
        if request.save_files and request.output_basename:
            from app.output_manager import _sanitize_filename

            safe_basename = (
                _sanitize_filename(request.output_basename.strip()) or "result"
            )
            run_output_dir = os.path.join(output_dir, f"{safe_basename}_results")
            Path(run_output_dir).mkdir(parents=True, exist_ok=True)

        file_paths = {"input_image": None, "overlay_image": None, "masked_segments": []}

        if boxes.numel() > 0:
            masks_for_viz = masks.squeeze(1) if masks.dim() > 2 else masks
            result_image = create_result_image(
                original_image=pil_image,
                boxes=boxes,
                masks=masks_for_viz,
                scores=scores,
                labels=labels,
            )
            result_base64 = image_to_base64(result_image)

            inference_time = time.time() - start_time
            metadata = generate_metadata(
                original_image=pil_image,
                text_prompt=request.text_prompt,
                boxes=boxes,
                masks=masks_for_viz,
                scores=scores,
                device=state.device,
                confidence_threshold=threshold,
                model_resolution=config.image_resolution,
                inference_time=inference_time,
                file_paths=file_paths,
                detection_labels=labels,
            )

            optional_files = None
            if request.save_files:
                result_bytes = base64.b64decode(result_base64)
                save_dir = run_output_dir if run_output_dir else output_dir
                result_path = await save_result_image(result_bytes, save_dir)
                file_paths["overlay_image"] = result_path
                metadata["file_paths"] = file_paths
                original_fn = (
                    request.output_basename.strip() if request.output_basename else None
                )
                metadata_path = await save_metadata(
                    metadata, save_dir, original_filename=original_fn
                )
                if (
                    run_output_dir
                    and (
                        request.save_segments_separately
                        or config.save_segments_separately
                    )
                    and per_prompt_masks
                ):
                    timestamp = int(time.time())
                    for masks_for_prompt, prompt in per_prompt_masks:
                        segment_paths = await save_masked_segments(
                            masks=masks_for_prompt,
                            original_image=pil_image,
                            text_prompt=prompt,
                            output_path=run_output_dir,
                            timestamp=timestamp,
                        )
                        file_paths["masked_segments"].extend(segment_paths)
                    metadata["file_paths"] = file_paths
                optional_files = {
                    "result_image_path": result_path,
                    "metadata_path": metadata_path,
                }

            return SegmentResponse(
                success=True,
                device_used=state.device,
                inference_time_ms=round(inference_time * 1000, 2),
                result_image_base64=result_base64,
                result_image_format="png",
                metadata=metadata,
                optional_files=optional_files,
            )
        else:
            inference_time = time.time() - start_time
            metadata = generate_metadata(
                original_image=pil_image,
                text_prompt=request.text_prompt,
                boxes=torch.tensor([]),
                masks=torch.tensor([]),
                scores=torch.tensor([]),
                device=state.device,
                confidence_threshold=threshold,
                model_resolution=config.image_resolution,
                inference_time=inference_time,
                file_paths=file_paths,
            )
            result_base64 = image_to_base64(pil_image)

            optional_files = None
            if request.save_files:
                result_bytes = base64.b64decode(result_base64)
                save_dir = run_output_dir if run_output_dir else output_dir
                result_path = await save_result_image(result_bytes, save_dir)
                file_paths["overlay_image"] = result_path
                metadata["file_paths"] = file_paths
                original_fn = (
                    request.output_basename.strip() if request.output_basename else None
                )
                metadata_path = await save_metadata(
                    metadata, save_dir, original_filename=original_fn
                )
                optional_files = {
                    "result_image_path": result_path,
                    "metadata_path": metadata_path,
                }

            return SegmentResponse(
                success=True,
                device_used=state.device,
                inference_time_ms=round(inference_time * 1000, 2),
                result_image_base64=result_base64,
                result_image_format="png",
                metadata=metadata,
                optional_files=optional_files,
            )

    except Exception as e:
        logger.error(f"Segmentation failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/cleanup-gpu", tags=["Maintenance"])
async def cleanup_gpu():
    """Manually cleanup GPU memory by resetting the processor.

    Use this endpoint between batches or when OOM errors occur to clear GPU memory.
    The model stays loaded, only the processor is recreated.

    Returns:
        JSON with cleanup status and memory info
    """
    try:
        _log_memory_usage("Before cleanup: ")

        if state.model is not None and state.processor is not None:
            from sam3.model.sam3_image_processor import Sam3Processor

            config = app_config.get_config()
            state.processor = Sam3Processor(
                model=state.model,
                device=state.device,
                confidence_threshold=config.confidence_threshold,
            )
            logger.info("GPU cleanup: Processor reset complete")
        else:
            logger.warning("GPU cleanup: No model loaded, nothing to cleanup")

        _cleanup_gpu_memory()
        _log_memory_usage("After cleanup: ")

        return {
            "success": True,
            "message": "GPU memory cleanup completed",
            "model_loaded": state.model is not None,
            "processor_reset": True,
        }

    except Exception as e:
        logger.error(f"GPU cleanup failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/config", response_model=ModelConfig, tags=["Configuration"])
async def get_config():
    """Get current model configuration."""
    return app_config.get_config()


@app.post("/api/update-config", tags=["Configuration"])
async def update_config(
    request: Request,
    confidence_threshold: Optional[float] = Form(None, ge=0, le=1),
    image_resolution: Optional[int] = Form(None, ge=224, le=2048),
    enable_instance_interactivity: Optional[str] = Form(None),
    model_compilation: Optional[str] = Form(None),
    save_segments_separately: Optional[str] = Form(None),
    save_combined_mask_per_label: Optional[str] = Form(None),
    save_all_combined_mask: Optional[str] = Form(None),
    show_bounding_box_labels: Optional[str] = Form(None),
    corner_annotation_enabled: Optional[str] = Form(None),
):
    """Update SAM model configuration dynamically.

    Note: Some configuration changes (like model_compilation or enable_instance_interactivity)
    may require model reload to take effect.
    """
    config = app_config.get_config()
    model_reload_needed = False

    if confidence_threshold is not None:
        config.confidence_threshold = confidence_threshold
        if state.processor:
            state.processor.confidence_threshold = confidence_threshold

    if image_resolution is not None:
        config.image_resolution = image_resolution
        # Note: Changing resolution requires recreating processor
        logger.warning(
            "Image resolution change requires model reload to take full effect"
        )

    if enable_instance_interactivity is not None:
        enable_instance_interactivity_bool = enable_instance_interactivity.lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
        if config.enable_instance_interactivity != enable_instance_interactivity_bool:
            config.enable_instance_interactivity = enable_instance_interactivity_bool
            model_reload_needed = True

    if model_compilation is not None:
        model_compilation_bool = model_compilation.lower() in ("true", "1", "yes", "on")
        if config.model_compilation != model_compilation_bool:
            config.model_compilation = model_compilation_bool
            model_reload_needed = True

    if save_segments_separately is not None:
        save_segments_separately_bool = save_segments_separately.lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
        config.save_segments_separately = save_segments_separately_bool
        logger.info(
            f"Config updated: save_segments_separately = {save_segments_separately_bool}"
        )

    if save_combined_mask_per_label is not None:
        save_combined_mask_per_label_bool = save_combined_mask_per_label.lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
        config.save_combined_mask_per_label = save_combined_mask_per_label_bool
        logger.info(
            f"Config updated: save_combined_mask_per_label = {save_combined_mask_per_label_bool}"
        )

    if save_all_combined_mask is not None:
        save_all_combined_mask_bool = save_all_combined_mask.lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
        config.save_all_combined_mask = save_all_combined_mask_bool
        logger.info(
            f"Config updated: save_all_combined_mask = {save_all_combined_mask_bool}"
        )

    if show_bounding_box_labels is not None:
        show_bounding_box_labels_bool = show_bounding_box_labels.lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
        config.show_bounding_box_labels = show_bounding_box_labels_bool
        logger.info(
            f"Config updated: show_bounding_box_labels = {show_bounding_box_labels_bool}"
        )

    if corner_annotation_enabled is not None:
        corner_annotation_enabled_bool = corner_annotation_enabled.lower() in (
            "true",
            "1",
            "yes",
            "on",
        )
        config.corner_annotation_enabled = corner_annotation_enabled_bool
        logger.info(
            f"Config updated: corner_annotation_enabled = {corner_annotation_enabled_bool}"
        )

    # Save configuration to file for persistence
    app_config.save_config()

    # Reload model if needed
    if model_reload_needed and state.model_loaded:
        logger.info("Configuration change requires model reload...")
        try:
            state.model_loaded = False
            state.model = None
            state.processor = None
            load_model()
        except Exception as e:
            logger.error(f"Failed to reload model: {e}")
            return {
                "success": False,
                "message": f"Configuration updated but model reload failed: {e}",
                "config": config.model_dump(),
            }

    try:
        return {
            "success": True,
            "message": "Configuration updated successfully",
            "config": config.model_dump(),
            "model_reloaded": model_reload_needed,
        }
    except Exception as return_err:
        logger.error(f"Error returning response: {return_err}")
        raise HTTPException(
            status_code=500, detail=f"Error generating response: {str(return_err)}"
        )


@app.post("/api/config", response_model=ModelConfig, tags=["Configuration"])
async def update_config(config_update: ModelConfig):
    """Update model configuration."""
    updated = app_config.update_config(**config_update.model_dump(exclude_unset=True))

    if state.model_loaded:
        state.processor.confidence_threshold = updated.confidence_threshold

    return updated


@app.get("/api/download", tags=["Files"])
async def download_file(
    path: str = Query(..., description="Path to file to download (must be within allowed_base_paths)"),
):
    """Download a file from the specified path.

    The path must be within allowed base directories (e.g., /outputs, /data, /mnt/share).
    """
    config = app_config.get_config()
    try:
        validated_path = validate_file_path(
            file_path=path,
            allowed_base_paths=config.allowed_base_paths,
            network_storage_enabled=config.network_storage_enabled,
            network_path_whitelist=config.network_path_whitelist,
        )
        return FileResponse(
            path=validated_path,
            filename=os.path.basename(validated_path),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading file {path}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/gui", tags=["GUI"])
async def serve_gui():
    """Serve GUI interface (optional, on-demand)."""
    gui_path = os.path.join(os.path.dirname(__file__), "static", "index.html")
    if os.path.exists(gui_path):
        from fastapi.responses import Response

        with open(gui_path, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(
            content=content,
            media_type="text/html",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Expires": "0",
            },
        )
    else:
        raise HTTPException(status_code=404, detail="GUI not available")


@app.get("/favicon.ico", tags=["Static"])
async def favicon():
    """Return empty favicon to prevent 404 errors."""
    from fastapi.responses import Response

    return Response(content=b"", media_type="image/x-icon")


@app.get("/", tags=["Info"])
async def root():
    """Root endpoint with API information."""
    return {
        "service": "SAM3 Segmentation API",
        "version": "1.0.0",
        "device": state.device,
        "model_loaded": state.model_loaded,
        "endpoints": {
            "health": "/health",
            "segment": "/api/segment",
            "segment_json": "/api/segment/json",
            "config": "/api/config",
            "gui": "/gui",
            "docs": "/docs",
            "howto": "/howto",
        },
    }


@app.get("/howto", tags=["Info"])
async def howto():
    """Detailed API usage guide with all endpoints and interaction examples."""
    return {
        "title": "SAM3 Segmentation API - Usage Guide",
        "description": "Production API for Meta's Segment Anything Model 3 (SAM3) with GPU acceleration",
        "base_url": "http://localhost:8222",
        "endpoints": {
            "health": {
                "method": "GET",
                "url": "/health",
                "description": "Check service health and GPU status",
                "authentication": "None",
                "parameters": {},
                "response": {
                    "status": "healthy|degraded",
                    "device": "cuda|cpu|mps",
                    "gpu_name": "NVIDIA RTX",
                    "model_loaded": True,
                    "model_downloaded": True
                },
                "example": {
                    "request": "curl http://localhost:8222/health",
                    "response": {"status": "healthy", "device": "cuda", "model_loaded": True}
                }
            },
            "model_status": {
                "method": "GET",
                "url": "/api/model-status",
                "description": "Check if SAM3 model is downloaded and loaded",
                "authentication": "None",
                "parameters": {},
                "response": {
                    "downloaded": True,
                    "path": "/models/huggingface/hub/models--facebook--sam3/snapshots/xxx/sam3.pt",
                    "model_loaded": True,
                    "device": "cuda"
                },
                "example": {
                    "request": "curl http://localhost:8222/api/model-status"
                }
            },
            "set_token": {
                "method": "POST",
                "url": "/api/set-token",
                "description": "Set HuggingFace token for model download (token is cleared after use for security)",
                "authentication": "None",
                "parameters": {"token": "Your HuggingFace access token"},
                "request_body": {
                    "token": "hf_xxxxxxxxxxxx"
                },
                "response": {
                    "success": True,
                    "message": "Token set successfully. Model will be downloaded on first use."
                },
                "example": {
                    "request": "curl -X POST http://localhost:8222/api/set-token -H 'Content-Type: application/json' -d '{\"token\": \"hf_xxxx\"}'"
                }
            },
            "download_model": {
                "method": "POST",
                "url": "/api/download-model",
                "description": "Trigger model download and loading (requires token to be set first)",
                "authentication": "Token must be set via /api/set-token",
                "parameters": {},
                "response": {
                    "success": True,
                    "message": "Model downloaded and loaded successfully!",
                    "model_loaded": True
                },
                "example": {
                    "request": "curl -X POST http://localhost:8222/api/download-model"
                }
            },
            "segment": {
                "method": "POST",
                "url": "/api/segment",
                "description": "Segment objects in an image using text prompts (main endpoint)",
                "authentication": "None (requires model to be loaded)",
                "content_type": "multipart/form-data",
                "parameters": {
                    "file_path": "Path to image file (local or network share)",
                    "text_prompt": "Objects to segment (comma-separated for multiple prompts)",
                    "output_folder": "Optional: custom output folder path",
                    "save_segments_separately": "Optional: 'true'/'false' - save individual masks",
                    "confidence_threshold": "Optional: 0.0-1.0 override",
                    "image_resolution": "Optional: 224-2048 override"
                },
                "request_format": "FormData (multipart/form-data)",
                "file_path_examples": {
                    "local": "/mnt/MAATI-Bot_data/raw_capture/image.jpg",
                    "network_windows": "\\\\192.168.1.50\\share\\image.jpg",
                    "network_linux": "//192.168.1.50/share/image.jpg"
                },
                "response": {
                    "success": True,
                    "device_used": "cuda",
                    "inference_time_ms": 1250.5,
                    "result_image_base64": "base64_encoded_overlay_image",
                    "metadata": {
                        "objects_detected": 3,
                        "labels": ["person", "plant", "vehicle"],
                        "boxes": "[[x1,y1,x2,y2], ...]",
                        "confidence_scores": [0.95, 0.87, 0.72],
                        "file_paths": {
                            "overlay_image": "/outputs/image_results/overlay.png",
                            "masked_segments": ["path1", "path2"]
                        }
                    }
                },
                "n8n_integration": {
                    "description": "In n8n HTTP Request node:",
                    "steps": [
                        "1. Set Body Content Type to 'Form-Data'",
                        "2. Add 'file_path' field as String: /path/to/image.jpg",
                        "3. Add 'text_prompt' field as String: person, plant",
                        "4. Add 'save_segments_separately' as String: true",
                        "5. Execute request"
                    ],
                    "binary_file_note": "If sending binary image data directly, use 'image' field with Binary File type, not String"
                },
                "example": {
                    "request": "curl -X POST http://localhost:8222/api/segment -F 'file_path=/mnt/MAATI-Bot_data/raw_capture/photo.jpg' -F 'text_prompt=person, vehicle'",
                    "python": "requests.post('http://localhost:8222/api/segment', data={'file_path': '/path/to/image.jpg', 'text_prompt': 'person'})"
                }
            },
            "segment_json": {
                "method": "POST",
                "url": "/api/segment/json",
                "description": "Segment using JSON body with base64-encoded image (deprecated, use /api/segment instead)",
                "authentication": "None",
                "content_type": "application/json",
                "request_body": {
                    "image_base64": "base64_encoded_image_string",
                    "text_prompt": "Objects to segment",
                    "confidence_threshold": 0.5,
                    "save_files": True,
                    "output_basename": "optional_output_name"
                },
                "response": "Same as /api/segment",
                "note": "This endpoint is kept for backward compatibility but is deprecated"
            },
            "cleanup_gpu": {
                "method": "POST",
                "url": "/api/cleanup-gpu",
                "description": "Free GPU memory between batch processing (model stays loaded)",
                "authentication": "None",
                "use_case": "Call this before processing new batch if you get OOM errors",
                "response": {
                    "success": True,
                    "message": "GPU memory cleanup completed",
                    "processor_reset": True
                },
                "example": {
                    "request": "curl -X POST http://localhost:8222/api/cleanup-gpu"
                }
            },
            "config": {
                "method": "GET",
                "url": "/api/config",
                "description": "Get current model configuration",
                "authentication": "None",
                "response": {
                    "confidence_threshold": 0.5,
                    "image_resolution": 1024,
                    "enable_instance_interactivity": False,
                    "model_compilation": False,
                    "save_segments_separately": True
                }
            },
            "update_config": {
                "method": "POST",
                "url": "/api/update-config",
                "description": "Update model configuration dynamically",
                "authentication": "None",
                "content_type": "multipart/form-data",
                "parameters": {
                    "confidence_threshold": "0.0-1.0",
                    "image_resolution": "224-2048",
                    "enable_instance_interactivity": "'true'/'false'",
                    "model_compilation": "'true'/'false'",
                    "save_segments_separately": "'true'/'false'"
                },
                "note": "Some changes require model reload"
            },
            "gui": {
                "method": "GET",
                "url": "/gui",
                "description": "Web-based GUI for manual testing",
                "authentication": "None",
                "usage": "Open http://localhost:8222/gui in browser"
            }
        },
        "workflow_integration": {
            "n8n": {
                "recommended_endpoint": "/api/segment",
                "body_type": "Form-Data",
                "required_fields": ["file_path", "text_prompt"],
                "optional_fields": ["save_segments_separately", "output_folder"],
                "timeout_note": "Set timeout to 60+ seconds for large images"
            },
            "curl_examples": {
                "basic_segmentation": "curl -X POST http://localhost:8222/api/segment -F 'file_path=/path/to/image.jpg' -F 'text_prompt=person'",
                "multiple_prompts": "curl -X POST http://localhost:8222/api/segment -F 'file_path=/path/to/image.jpg' -F 'text_prompt=person, vehicle, plant'",
                "save_masks": "curl -X POST http://localhost:8222/api/segment -F 'file_path=/path/to/image.jpg' -F 'text_prompt=person' -F 'save_segments_separately=true'"
            }
        },
        "error_codes": {
            "400": "Bad request - invalid parameters or encoding issue",
            "403": "Access denied - path not in allowed directories",
            "404": "File not found",
            "500": "Internal error - check error detail message",
            "503": "Model not loaded - call /api/download-model first"
        }
    }


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Global exception handler to prevent crashes."""
    logger.error(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error": str(exc)},
    )
