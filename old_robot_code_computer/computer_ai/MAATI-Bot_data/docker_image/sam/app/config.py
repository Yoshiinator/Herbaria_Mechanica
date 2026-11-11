"""
Configuration management for SAM3 FastAPI service.
"""
import json
import os
from pathlib import Path
from pydantic import BaseModel, Field
from typing import Optional


class ModelConfig(BaseModel):
    """Model configuration parameters."""
    confidence_threshold: float = Field(0.5, ge=0.0, le=1.0, description="Confidence threshold for detections")
    image_resolution: int = Field(1008, ge=224, le=2048, description="Input image resolution")
    enable_instance_interactivity: bool = Field(False, description="Enable SAM1-style instance interactivity")
    model_compilation: bool = Field(False, description="Enable torch.compile for model acceleration")
    save_segments_separately: bool = Field(False, description="Save individual masks and cropped objects separately")
    save_combined_mask_per_label: bool = Field(False, description="Save one image per unique label with all instances combined")
    save_all_combined_mask: bool = Field(False, description="Save single image with all labels grouped together")
    save_individual_crops_with_legend: bool = Field(True, description="Save individual crops with legend overlay")
    save_combined_per_label: bool = Field(True, description="Save combined per label")
    save_overlay_result: bool = Field(True, description="Save overlay result image")
    show_bounding_box_labels: bool = Field(True, description="Show labels on bounding boxes")
    corner_annotation_enabled: bool = Field(True, description="Show label/count/confidence in image corner")
    corner_annotation_position: str = Field("bottom-right", description="Corner position: top-left, top-right, bottom-left, bottom-right")
    allowed_base_paths: list[str] = Field(default_factory=lambda: ["/home/node/.n8n-files", "/data", "/mnt"], description="Allowed base directories for file access")
    network_storage_enabled: bool = Field(True, description="Enable network storage path support")
    result_storage_path: Optional[str] = Field(None, description="Network path for saving results (e.g., \\nas-server\results or //nas-server/results)")
    network_path_whitelist: Optional[list[str]] = Field(None, description="Optional list of allowed server/share combinations (e.g., [\"\\\\nas-server\\share\"])")


class ConfigManager:
    """Manages application configuration."""
    
    def __init__(self, config_file_path: Optional[str] = None):
        """Initialize ConfigManager with optional config file path.
        
        Args:
            config_file_path: Path to JSON config file. Defaults to /app/config.json
        """
        if config_file_path is None:
            # Default to /outputs/config.json (persistent across container restarts via volume mount)
            # Can be overridden with CONFIG_FILE_PATH env var
            config_file_path = os.getenv("CONFIG_FILE_PATH", "/outputs/config.json")
        
        self._config_file_path = Path(config_file_path)
        
        # Try to load from file first
        config_data = self.load_config()
        
        if config_data:
            # Config loaded from file - use it
            self._config = ModelConfig(**config_data)
        else:
            # No config file - load from environment variables
            allowed_paths_str = os.getenv("ALLOWED_BASE_PATHS", "/home/node/.n8n-files,/data,/mnt,/mnt/share,/n8n_results,/outputs")
            allowed_paths = [p.strip() for p in allowed_paths_str.split(",") if p.strip()]
            network_enabled = os.getenv("NETWORK_STORAGE_ENABLED", "true").lower() == "true"
            
            # Load result storage path (network path for saving results)
            result_storage_path = os.getenv("RESULT_STORAGE_PATH", "/home/node/.n8n-files/results")
            
            # Load network path whitelist (optional security feature)
            # Default to allowing the 192.168.1.2/SharedFiles network path
            network_whitelist_str = os.getenv("NETWORK_PATH_WHITELIST", "//192.168.1.2/SharedFiles")
            network_whitelist = None
            if network_whitelist_str:
                network_whitelist = [p.strip() for p in network_whitelist_str.split(",") if p.strip()]
            
            # Load new output options
            save_combined_mask_per_label = os.getenv("SAVE_COMBINED_MASK_PER_LABEL", "false").lower() == "true"
            save_all_combined_mask = os.getenv("SAVE_ALL_COMBINED_MASK", "false").lower() == "true"
            save_individual_crops_with_legend = os.getenv("SAVE_INDIVIDUAL_CROPS_WITH_LEGEND", "true").lower() == "true"
            save_combined_per_label = os.getenv("SAVE_COMBINED_PER_LABEL", "true").lower() == "true"
            save_overlay_result = os.getenv("SAVE_OVERLAY_RESULT", "true").lower() == "true"
            show_bounding_box_labels = os.getenv("SHOW_BOUNDING_BOX_LABELS", "true").lower() == "true"
            corner_annotation_enabled = os.getenv("CORNER_ANNOTATION_ENABLED", "true").lower() == "true"
            corner_annotation_position = os.getenv("CORNER_ANNOTATION_POSITION", "bottom-right")

            self._config = ModelConfig(
                allowed_base_paths=allowed_paths,
                network_storage_enabled=network_enabled,
                result_storage_path=result_storage_path,
                network_path_whitelist=network_whitelist,
                save_combined_mask_per_label=save_combined_mask_per_label,
                save_all_combined_mask=save_all_combined_mask,
                save_individual_crops_with_legend=save_individual_crops_with_legend,
                save_combined_per_label=save_combined_per_label,
                save_overlay_result=save_overlay_result,
                show_bounding_box_labels=show_bounding_box_labels,
                corner_annotation_enabled=corner_annotation_enabled,
                corner_annotation_position=corner_annotation_position,
            )
            
            # Save default config to file
            self.save_config()
    
    def load_config(self) -> Optional[dict]:
        """Load configuration from JSON file.
        
        Returns:
            Dictionary with config data if file exists, None otherwise
        """
        if not self._config_file_path.exists():
            return None
        
        try:
            with open(self._config_file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(f"Failed to load config from {self._config_file_path}: {e}")
            return None
    
    def save_config(self) -> bool:
        """Save current configuration to JSON file.
        
        Returns:
            True if saved successfully, False otherwise
        """
        try:
            # Ensure directory exists
            self._config_file_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Convert config to dict and save
            config_dict = self._config.model_dump()
            with open(self._config_file_path, 'w', encoding='utf-8') as f:
                json.dump(config_dict, f, indent=2, ensure_ascii=False)
            
            import logging
            logger = logging.getLogger(__name__)
            logger.info(f"Configuration saved to {self._config_file_path}")
            return True
        except (IOError, OSError) as e:
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Failed to save config to {self._config_file_path}: {e}")
            return False
    
    def get_config(self) -> ModelConfig:
        """Get current configuration."""
        return self._config
    
    def update_config(self, **kwargs) -> ModelConfig:
        """Update configuration with new values."""
        for key, value in kwargs.items():
            if hasattr(self._config, key):
                setattr(self._config, key, value)
        return self._config


# Global configuration instance
app_config = ConfigManager()
