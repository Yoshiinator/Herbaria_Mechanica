// DOM Elements - Model Download
const modelStatusText = document.getElementById('model-status-text');
const tokenSection = document.getElementById('token-section');
const hfTokenInput = document.getElementById('hf-token');
const downloadModelBtn = document.getElementById('download-model-btn');
const downloadStatus = document.getElementById('download-status');
const redownloadSection = document.getElementById('redownload-section');
const redownloadModelBtn = document.getElementById('redownload-model-btn');
const modelPanel = document.getElementById('model-panel');

// DOM Elements - Configuration
const outputFolderInput = document.getElementById('output-folder');
const imageResolutionInput = document.getElementById('image-resolution');
const confidenceThresholdInput = document.getElementById('confidence-threshold');
const enableInstanceInteractivityInput = document.getElementById('enable-instance-interactivity');
const modelCompilationInput = document.getElementById('model-compilation');
const saveSegmentsSeparatelyInput = document.getElementById('save-segments-separately');
const saveCombinedMaskPerLabelInput = document.getElementById('save-combined-mask-per-label');
const saveAllCombinedMaskInput = document.getElementById('save-all-combined-mask');
const showBoundingBoxLabelsInput = document.getElementById('show-bounding-box-labels');
const cornerAnnotationEnabledInput = document.getElementById('corner-annotation-enabled');
const saveConfigBtn = document.getElementById('save-config-btn');
const configSaveStatus = document.getElementById('config-save-status');

// DOM Elements - Image Processing
const filePathInput = document.getElementById('file-path');
const textPromptInput = document.getElementById('text-prompt');
const processBtn = document.getElementById('process-btn');
const resultArea = document.getElementById('result-area');
const resultImage = document.getElementById('result-image');
const metadataDisplay = document.getElementById('metadata-display');

let modelDownloaded = false;

// Configuration persistence keys
const CONFIG_STORAGE_KEY = 'sam3_config';

// Load saved configuration from localStorage
function loadSavedConfig() {
    try {
        const saved = localStorage.getItem(CONFIG_STORAGE_KEY);
        if (saved) {
            const config = JSON.parse(saved);
            
            // Re-lookup elements to ensure they exist
            const outputFolderEl = document.getElementById('output-folder');
            const imageResolutionEl = document.getElementById('image-resolution');
            const confidenceThresholdEl = document.getElementById('confidence-threshold');
            const enableInstanceInteractivityEl = document.getElementById('enable-instance-interactivity');
            const modelCompilationEl = document.getElementById('model-compilation');
            const saveSegmentsSeparatelyEl = document.getElementById('save-segments-separately');
            const saveCombinedMaskPerLabelEl = document.getElementById('save-combined-mask-per-label');
            const saveAllCombinedMaskEl = document.getElementById('save-all-combined-mask');
            const showBoundingBoxLabelsEl = document.getElementById('show-bounding-box-labels');
            const cornerAnnotationEnabledEl = document.getElementById('corner-annotation-enabled');
            
            if (config.outputFolder !== undefined && outputFolderEl) {
                outputFolderEl.value = config.outputFolder;
            }
            if (config.imageResolution !== undefined && imageResolutionEl) {
                imageResolutionEl.value = config.imageResolution;
            }
            if (config.confidenceThreshold !== undefined && confidenceThresholdEl) {
                confidenceThresholdEl.value = config.confidenceThreshold;
            }
            if (config.enableInstanceInteractivity !== undefined && enableInstanceInteractivityEl) {
                enableInstanceInteractivityEl.checked = config.enableInstanceInteractivity;
            }
            if (config.modelCompilation !== undefined && modelCompilationEl) {
                modelCompilationEl.checked = config.modelCompilation;
            }
            if (config.saveSegmentsSeparately !== undefined && saveSegmentsSeparatelyEl) {
                saveSegmentsSeparatelyEl.checked = Boolean(config.saveSegmentsSeparately);
            }
            if (config.saveCombinedMaskPerLabel !== undefined && saveCombinedMaskPerLabelEl) {
                saveCombinedMaskPerLabelEl.checked = Boolean(config.saveCombinedMaskPerLabel);
            }
            if (config.saveAllCombinedMask !== undefined && saveAllCombinedMaskEl) {
                saveAllCombinedMaskEl.checked = Boolean(config.saveAllCombinedMask);
            }
            if (config.showBoundingBoxLabels !== undefined && showBoundingBoxLabelsEl) {
                showBoundingBoxLabelsEl.checked = Boolean(config.showBoundingBoxLabels);
            }
            if (config.cornerAnnotationEnabled !== undefined && cornerAnnotationEnabledEl) {
                cornerAnnotationEnabledEl.checked = Boolean(config.cornerAnnotationEnabled);
            }
        }
    } catch (error) {
        console.error('Error loading saved config:', error);
    }
}

// Save configuration to localStorage
function saveConfigToStorage() {
    try {
        // Re-lookup elements to ensure they exist (DOM might not be ready when script loads)
        const outputFolderEl = document.getElementById('output-folder');
        const imageResolutionEl = document.getElementById('image-resolution');
        const confidenceThresholdEl = document.getElementById('confidence-threshold');
        const enableInstanceInteractivityEl = document.getElementById('enable-instance-interactivity');
        const modelCompilationEl = document.getElementById('model-compilation');
        const saveSegmentsSeparatelyEl = document.getElementById('save-segments-separately');
        const saveCombinedMaskPerLabelEl = document.getElementById('save-combined-mask-per-label');
        const saveAllCombinedMaskEl = document.getElementById('save-all-combined-mask');
        const showBoundingBoxLabelsEl = document.getElementById('show-bounding-box-labels');
        const cornerAnnotationEnabledEl = document.getElementById('corner-annotation-enabled');
        
        // Get current values from form elements (with null checks)
        const config = {
            outputFolder: outputFolderEl ? outputFolderEl.value : '',
            imageResolution: imageResolutionEl ? parseFloat(imageResolutionEl.value) : 1008,
            confidenceThreshold: confidenceThresholdEl ? parseFloat(confidenceThresholdEl.value) : 0.5,
            enableInstanceInteractivity: enableInstanceInteractivityEl ? enableInstanceInteractivityEl.checked : false,
            modelCompilation: modelCompilationEl ? modelCompilationEl.checked : false,
            saveSegmentsSeparately: saveSegmentsSeparatelyEl ? saveSegmentsSeparatelyEl.checked : false,
            saveCombinedMaskPerLabel: saveCombinedMaskPerLabelEl ? saveCombinedMaskPerLabelEl.checked : false,
            saveAllCombinedMask: saveAllCombinedMaskEl ? saveAllCombinedMaskEl.checked : false,
            showBoundingBoxLabels: showBoundingBoxLabelsEl ? showBoundingBoxLabelsEl.checked : true,
            cornerAnnotationEnabled: cornerAnnotationEnabledEl ? cornerAnnotationEnabledEl.checked : true
        };
        localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(config));
    } catch (error) {
        console.error('Error saving config to storage:', error);
    }
}

// Load configuration from API
async function loadConfigFromAPI() {
    try {
        const response = await fetch('/api/config');
        if (response.ok) {
            const config = await response.json();
            // Return config so caller can use it
            
            // Re-lookup elements to ensure they exist (DOM might not be ready when script loads)
            const confidenceThresholdEl = document.getElementById('confidence-threshold');
            const imageResolutionEl = document.getElementById('image-resolution');
            const enableInstanceInteractivityEl = document.getElementById('enable-instance-interactivity');
            const modelCompilationEl = document.getElementById('model-compilation');
            const saveSegmentsSeparatelyEl = document.getElementById('save-segments-separately');
            const saveCombinedMaskPerLabelEl = document.getElementById('save-combined-mask-per-label');
            const saveAllCombinedMaskEl = document.getElementById('save-all-combined-mask');
            const showBoundingBoxLabelsEl = document.getElementById('show-bounding-box-labels');
            const cornerAnnotationEnabledEl = document.getElementById('corner-annotation-enabled');
            const outputFolderEl = document.getElementById('output-folder');
            
            // Update all form fields from API (source of truth)
            if (config.confidence_threshold !== undefined && confidenceThresholdEl) {
                confidenceThresholdEl.value = config.confidence_threshold;
            }
            if (config.image_resolution !== undefined && imageResolutionEl) {
                imageResolutionEl.value = config.image_resolution;
            }
            if (config.enable_instance_interactivity !== undefined && enableInstanceInteractivityEl) {
                enableInstanceInteractivityEl.checked = Boolean(config.enable_instance_interactivity);
            }
            if (config.model_compilation !== undefined && modelCompilationEl) {
                modelCompilationEl.checked = Boolean(config.model_compilation);
            }
            if (config.save_segments_separately !== undefined && saveSegmentsSeparatelyEl) {
                saveSegmentsSeparatelyEl.checked = Boolean(config.save_segments_separately);
            }
            if (config.save_combined_mask_per_label !== undefined && saveCombinedMaskPerLabelEl) {
                saveCombinedMaskPerLabelEl.checked = Boolean(config.save_combined_mask_per_label);
            }
            if (config.save_all_combined_mask !== undefined && saveAllCombinedMaskEl) {
                saveAllCombinedMaskEl.checked = Boolean(config.save_all_combined_mask);
            }
            if (config.show_bounding_box_labels !== undefined && showBoundingBoxLabelsEl) {
                showBoundingBoxLabelsEl.checked = Boolean(config.show_bounding_box_labels);
            }
            if (config.corner_annotation_enabled !== undefined && cornerAnnotationEnabledEl) {
                cornerAnnotationEnabledEl.checked = Boolean(config.corner_annotation_enabled);
            }
            if (config.result_storage_path !== undefined && outputFolderEl) {
                outputFolderEl.value = config.result_storage_path;
            }
            
            // Save API config to localStorage for fallback (using API values directly, not DOM)
            try {
                const configForStorage = {
                    outputFolder: config.result_storage_path || (outputFolderEl ? outputFolderEl.value : ''),
                    imageResolution: config.image_resolution !== undefined ? config.image_resolution : (imageResolutionEl ? parseFloat(imageResolutionEl.value) : 1008),
                    confidenceThreshold: config.confidence_threshold !== undefined ? config.confidence_threshold : (confidenceThresholdEl ? parseFloat(confidenceThresholdEl.value) : 0.5),
                    enableInstanceInteractivity: config.enable_instance_interactivity !== undefined ? Boolean(config.enable_instance_interactivity) : (enableInstanceInteractivityEl ? enableInstanceInteractivityEl.checked : false),
                    modelCompilation: config.model_compilation !== undefined ? Boolean(config.model_compilation) : (modelCompilationEl ? modelCompilationEl.checked : false),
                    saveSegmentsSeparately: config.save_segments_separately !== undefined ? Boolean(config.save_segments_separately) : (saveSegmentsSeparatelyEl ? saveSegmentsSeparatelyEl.checked : false),
                    saveCombinedMaskPerLabel: config.save_combined_mask_per_label !== undefined ? Boolean(config.save_combined_mask_per_label) : (saveCombinedMaskPerLabelEl ? saveCombinedMaskPerLabelEl.checked : false),
                    saveAllCombinedMask: config.save_all_combined_mask !== undefined ? Boolean(config.save_all_combined_mask) : (saveAllCombinedMaskEl ? saveAllCombinedMaskEl.checked : false),
                    showBoundingBoxLabels: config.show_bounding_box_labels !== undefined ? Boolean(config.show_bounding_box_labels) : (showBoundingBoxLabelsEl ? showBoundingBoxLabelsEl.checked : true),
                    cornerAnnotationEnabled: config.corner_annotation_enabled !== undefined ? Boolean(config.corner_annotation_enabled) : (cornerAnnotationEnabledEl ? cornerAnnotationEnabledEl.checked : true)
                };
                localStorage.setItem(CONFIG_STORAGE_KEY, JSON.stringify(configForStorage));
                console.log('Config saved to localStorage:', configForStorage);
            } catch (error) {
                console.error('Error saving config to localStorage:', error);
            }
            return config; // Return config for caller
        } else {
            // API failed - fall back to localStorage
            console.warn('Failed to load config from API, using localStorage fallback');
            loadSavedConfig();
            return null;
        }
    } catch (error) {
        console.error('Error loading config from API:', error);
        // API failed - fall back to localStorage
        loadSavedConfig();
        return null;
    }
}

// Save configuration to API
// Make function globally accessible
window.saveConfiguration = async function saveConfiguration() {
    // Re-lookup ALL elements to ensure we have current state (don't rely on global variables)
    const saveSegmentsSeparatelyInputCurrent = document.getElementById('save-segments-separately');
    const saveCombinedMaskPerLabelInputCurrent = document.getElementById('save-combined-mask-per-label');
    const saveAllCombinedMaskInputCurrent = document.getElementById('save-all-combined-mask');
    const showBoundingBoxLabelsInputCurrent = document.getElementById('show-bounding-box-labels');
    const cornerAnnotationEnabledInputCurrent = document.getElementById('corner-annotation-enabled');
    const enableInstanceInteractivityInputCurrent = document.getElementById('enable-instance-interactivity');
    const modelCompilationInputCurrent = document.getElementById('model-compilation');
    const confidenceThresholdInputCurrent = document.getElementById('confidence-threshold');
    const imageResolutionInputCurrent = document.getElementById('image-resolution');
    const saveConfigBtnCurrent = document.getElementById('save-config-btn');
    const configSaveStatusCurrent = document.getElementById('config-save-status');
    
    if (!saveConfigBtnCurrent || !configSaveStatusCurrent) {
        const errorMsg = 'Required DOM elements not found. Please refresh the page.';
        console.error(errorMsg);
        alert(errorMsg);
        return;
    }
    saveConfigBtnCurrent.disabled = true;
    configSaveStatusCurrent.textContent = 'Saving...';
    configSaveStatusCurrent.style.color = '#666';
    
    try {
        const formData = new FormData();
        
        // Always use re-looked-up elements, never global variables
        if (confidenceThresholdInputCurrent) {
            formData.append('confidence_threshold', confidenceThresholdInputCurrent.value);
        }
        
        if (imageResolutionInputCurrent) {
            formData.append('image_resolution', imageResolutionInputCurrent.value);
        }
        
        // Always send boolean values (true/false) so FastAPI can parse them correctly
        if (enableInstanceInteractivityInputCurrent) {
            formData.append('enable_instance_interactivity', enableInstanceInteractivityInputCurrent.checked ? 'true' : 'false');
        } else {
            formData.append('enable_instance_interactivity', 'false');
        }
        
        if (modelCompilationInputCurrent) {
            formData.append('model_compilation', modelCompilationInputCurrent.checked ? 'true' : 'false');
        } else {
            formData.append('model_compilation', 'false');
        }
        
        if (saveSegmentsSeparatelyInputCurrent) {
            formData.append('save_segments_separately', saveSegmentsSeparatelyInputCurrent.checked ? 'true' : 'false');
        } else {
            formData.append('save_segments_separately', 'false');
        }
        
        if (saveCombinedMaskPerLabelInputCurrent) {
            formData.append('save_combined_mask_per_label', saveCombinedMaskPerLabelInputCurrent.checked ? 'true' : 'false');
        } else {
            formData.append('save_combined_mask_per_label', 'false');
        }
        
        if (saveAllCombinedMaskInputCurrent) {
            formData.append('save_all_combined_mask', saveAllCombinedMaskInputCurrent.checked ? 'true' : 'false');
        } else {
            formData.append('save_all_combined_mask', 'false');
        }
        
        if (showBoundingBoxLabelsInputCurrent) {
            formData.append('show_bounding_box_labels', showBoundingBoxLabelsInputCurrent.checked ? 'true' : 'false');
        } else {
            formData.append('show_bounding_box_labels', 'true');
        }
        
        if (cornerAnnotationEnabledInputCurrent) {
            formData.append('corner_annotation_enabled', cornerAnnotationEnabledInputCurrent.checked ? 'true' : 'false');
        } else {
            formData.append('corner_annotation_enabled', 'true');
        }
        
        let response;
        try {
            response = await fetch('/api/update-config', {
                method: 'POST',
                body: formData
            });
        } catch (fetchError) {
            console.error('Fetch error:', fetchError);
            throw new Error(`Network error: ${fetchError.message}. Please check if the server is running.`);
        }
        
        const data = await response.json();
        
        // Re-lookup status element in case it changed
        const configSaveStatusFinal = document.getElementById('config-save-status');
        const saveConfigBtnFinal = document.getElementById('save-config-btn');
        
        if (response.ok && data.success) {
            if (configSaveStatusFinal) {
                configSaveStatusFinal.textContent = '✅ Configuration saved successfully!';
                configSaveStatusFinal.style.color = '#28a745';
            }
            
            // Save to localStorage
            saveConfigToStorage();
            
            // Clear status after 3 seconds
            setTimeout(() => {
                const statusEl = document.getElementById('config-save-status');
                if (statusEl) {
                    statusEl.textContent = '';
                }
            }, 3000);
        } else {
            throw new Error(data.message || 'Failed to save configuration');
        }
    } catch (error) {
        const errorMsg = error.message || String(error) || 'Unknown error';
        const configSaveStatusError = document.getElementById('config-save-status');
        if (configSaveStatusError) {
            configSaveStatusError.textContent = `❌ Error: ${errorMsg}`;
            configSaveStatusError.style.color = '#dc3545';
        }
        console.error('Error saving configuration:', error);
        // Also log to console with full details
        console.error('Full error object:', error);
        console.error('Error stack:', error.stack);
    } finally {
        const saveConfigBtnFinal = document.getElementById('save-config-btn');
        if (saveConfigBtnFinal) {
            saveConfigBtnFinal.disabled = false;
        }
    }
}

// Auto-save checkbox states to localStorage and API
function setupAutoSave() {
    // Re-lookup elements to ensure they exist
    const enableInstanceInteractivityEl = document.getElementById('enable-instance-interactivity');
    const modelCompilationEl = document.getElementById('model-compilation');
    const saveSegmentsSeparatelyEl = document.getElementById('save-segments-separately');
    const saveCombinedMaskPerLabelEl = document.getElementById('save-combined-mask-per-label');
    const saveAllCombinedMaskEl = document.getElementById('save-all-combined-mask');
    const showBoundingBoxLabelsEl = document.getElementById('show-bounding-box-labels');
    const cornerAnnotationEnabledEl = document.getElementById('corner-annotation-enabled');
    
    // Save checkbox states immediately when changed - both to localStorage and API
    if (enableInstanceInteractivityEl) {
        enableInstanceInteractivityEl.addEventListener('change', async () => {
            saveConfigToStorage();
            await saveConfiguration();
        });
    }
    
    if (modelCompilationEl) {
        modelCompilationEl.addEventListener('change', async () => {
            saveConfigToStorage();
            await saveConfiguration();
        });
    }
    
    if (saveSegmentsSeparatelyEl) {
        saveSegmentsSeparatelyEl.addEventListener('change', async () => {
            console.log('Checkbox changed to:', saveSegmentsSeparatelyEl.checked);
            saveConfigToStorage();
            await saveConfiguration();
            console.log('Checkbox state saved to backend');
        });
    }
    
    if (saveCombinedMaskPerLabelEl) {
        saveCombinedMaskPerLabelEl.addEventListener('change', async () => {
            console.log('saveCombinedMaskPerLabel changed to:', saveCombinedMaskPerLabelEl.checked);
            saveConfigToStorage();
            await saveConfiguration();
        });
    }
    
    if (saveAllCombinedMaskEl) {
        saveAllCombinedMaskEl.addEventListener('change', async () => {
            console.log('saveAllCombinedMask changed to:', saveAllCombinedMaskEl.checked);
            saveConfigToStorage();
            await saveConfiguration();
        });
    }
    
    if (showBoundingBoxLabelsEl) {
        showBoundingBoxLabelsEl.addEventListener('change', async () => {
            console.log('showBoundingBoxLabels changed to:', showBoundingBoxLabelsEl.checked);
            saveConfigToStorage();
            await saveConfiguration();
        });
    }
    
    if (cornerAnnotationEnabledEl) {
        cornerAnnotationEnabledEl.addEventListener('change', async () => {
            console.log('cornerAnnotationEnabled changed to:', cornerAnnotationEnabledEl.checked);
            saveConfigToStorage();
            await saveConfiguration();
        });
    }
    
    // Save other inputs on blur (when user leaves the field)
    outputFolderInput.addEventListener('blur', () => {
        saveConfigToStorage();
    });
    
    imageResolutionInput.addEventListener('blur', () => {
        saveConfigToStorage();
    });
    
    confidenceThresholdInput.addEventListener('blur', () => {
        saveConfigToStorage();
    });
}

// Check model status on page load
async function checkModelStatus() {
    try {
        const response = await fetch('/api/model-status');
        const data = await response.json();
        modelDownloaded = data.downloaded;
        updateModelUI(modelDownloaded);
    } catch (error) {
        console.error('Error checking model status:', error);
        modelStatusText.textContent = 'Error checking model status';
    }
}

function updateModelUI(downloaded) {
    modelPanel.style.display = 'block';
    tokenSection.style.display = 'block';
    
    if (downloaded) {
        modelStatusText.textContent = '✅ Model downloaded and ready';
        modelStatusText.style.color = '#28a745';
        tokenSection.style.display = 'none';
        redownloadSection.style.display = 'block';
    } else {
        modelStatusText.textContent = '❌ Model not downloaded - enter token to download';
        modelStatusText.style.color = '#dc3545';
        tokenSection.style.display = 'block';
        redownloadSection.style.display = 'none';
    }
}

function showRedownloadToken() {
    modelDownloaded = false;
    updateModelUI(false);
    hfTokenInput.value = '';
}

// Download model
async function downloadModel() {
    const token = hfTokenInput.value.trim();
    if (!token) {
        alert('Please enter your HuggingFace token');
        return;
    }
    
    downloadModelBtn.disabled = true;
    downloadStatus.textContent = 'Setting token...';
    
    try {
        // Set token
        const setTokenResponse = await fetch('/api/set-token', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({token: token})
        });
        
        if (!setTokenResponse.ok) {
            throw new Error('Failed to set token');
        }
        
        downloadStatus.textContent = 'Downloading model (this may take a few minutes)...';
        
        // Trigger download
        const downloadResponse = await fetch('/api/download-model', {
            method: 'POST'
        });
        
        const downloadData = await downloadResponse.json();
        
        if (downloadResponse.ok && downloadData.success) {
            downloadStatus.textContent = '✅ Model downloaded successfully!';
            downloadStatus.style.color = '#28a745';
            hfTokenInput.value = '';
            await checkModelStatus();
        } else {
            throw new Error(downloadData.detail || 'Download failed');
        }
    } catch (error) {
        downloadStatus.textContent = `❌ Error: ${error.message}`;
        downloadStatus.style.color = '#dc3545';
        console.error('Download error:', error);
    } finally {
        downloadModelBtn.disabled = false;
    }
}

// Process image
async function processImage() {
    if (!modelDownloaded) {
        alert('Model not downloaded. Please enter your HuggingFace token and download the model first.');
        return;
    }
    
    const filePath = filePathInput.value.trim();
    if (!filePath) {
        alert('Please enter a file path');
        return;
    }
    
    const textPrompt = textPromptInput.value.trim();
    if (!textPrompt) {
        alert('Please enter a text prompt');
        return;
    }
    
    processBtn.disabled = true;
    processBtn.textContent = 'Processing...';
    resultArea.style.display = 'none';
    
    try {
        const formData = new FormData();
        formData.append('file_path', filePath);
        formData.append('text_prompt', textPrompt);
        
        // Configuration parameters
        const outputFolder = outputFolderInput.value.trim();
        if (outputFolder) {
            formData.append('output_folder', outputFolder);
        }
        
        const confidenceThreshold = confidenceThresholdInput.value;
        if (confidenceThreshold) {
            formData.append('confidence_threshold', confidenceThreshold);
        }
        
        const imageResolution = imageResolutionInput.value;
        if (imageResolution) {
            formData.append('image_resolution', imageResolution);
        }
        
        if (enableInstanceInteractivityInput.checked) {
            formData.append('enable_instance_interactivity', 'true');
        }
        
        if (modelCompilationInput.checked) {
            formData.append('model_compilation', 'true');
        }
        
        // Always send boolean value (true/false) so FastAPI can parse it correctly
        // Read checkbox state directly from DOM to ensure we get the current value
        const checkboxElement = document.getElementById('save-segments-separately');
        const saveSegmentsValue = checkboxElement && checkboxElement.checked ? 'true' : 'false';
        formData.append('save_segments_separately', saveSegmentsValue);
        
        const saveCombinedMaskPerLabelElement = document.getElementById('save-combined-mask-per-label');
        const saveCombinedMaskPerLabelValue = saveCombinedMaskPerLabelElement && saveCombinedMaskPerLabelElement.checked ? 'true' : 'false';
        formData.append('save_combined_mask_per_label', saveCombinedMaskPerLabelValue);
        
        const saveAllCombinedMaskElement = document.getElementById('save-all-combined-mask');
        const saveAllCombinedMaskValue = saveAllCombinedMaskElement && saveAllCombinedMaskElement.checked ? 'true' : 'false';
        formData.append('save_all_combined_mask', saveAllCombinedMaskValue);
        
        const showBoundingBoxLabelsElement = document.getElementById('show-bounding-box-labels');
        const showBoundingBoxLabelsValue = showBoundingBoxLabelsElement && showBoundingBoxLabelsElement.checked ? 'true' : 'false';
        formData.append('show_bounding_box_labels', showBoundingBoxLabelsValue);
        
        const cornerAnnotationElement = document.getElementById('corner-annotation-enabled');
        const cornerAnnotationValue = cornerAnnotationElement && cornerAnnotationElement.checked ? 'true' : 'false';
        formData.append('corner_annotation_enabled', cornerAnnotationValue);
        
        
        const response = await fetch('/api/segment', {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        if (response.ok && data.success) {
            resultImage.src = 'data:image/png;base64,' + data.result_image_base64;
            
            // Display metadata with file paths highlighted
            let metadataHtml = '<h4>Metadata:</h4><pre>' + JSON.stringify(data.metadata, null, 2) + '</pre>';
            
            // Display file paths if available
            if (data.metadata && data.metadata.file_paths) {
                const filePaths = data.metadata.file_paths;
                metadataHtml += '<h4>File Paths:</h4><ul>';
                metadataHtml += '<li><strong>Input Image:</strong> ' + (filePaths.input_image || 'N/A') + '</li>';
                metadataHtml += '<li><strong>Overlay Image:</strong> ' + (filePaths.overlay_image || 'N/A') + '</li>';
                
                if (filePaths.masked_segments && filePaths.masked_segments.length > 0) {
                    metadataHtml += '<li><strong>Masked Segments:</strong><ul>';
                    filePaths.masked_segments.forEach(path => {
                        metadataHtml += '<li>' + path + '</li>';
                    });
                    metadataHtml += '</ul></li>';
                }
                
                // Combined masks per label
                if (filePaths.combined_masks_per_label && Object.keys(filePaths.combined_masks_per_label).length > 0) {
                    metadataHtml += '<li><strong>Combined Masks Per Label:</strong><ul>';
                    for (const [label, path] of Object.entries(filePaths.combined_masks_per_label)) {
                        metadataHtml += '<li>' + label + ': ' + path + '</li>';
                    }
                    metadataHtml += '</ul></li>';
                }
                
                // All combined mask
                if (filePaths.all_combined_mask) {
                    metadataHtml += '<li><strong>All Combined Mask:</strong> ' + filePaths.all_combined_mask + '</li>';
                }
                
                // Backward compatibility: show old keys if they exist
                if (filePaths.individual_masks && filePaths.individual_masks.length > 0) {
                    metadataHtml += '<li><strong>Individual Masks (legacy):</strong><ul>';
                    filePaths.individual_masks.forEach(path => {
                        metadataHtml += '<li>' + path + '</li>';
                    });
                    metadataHtml += '</ul></li>';
                }
                
                if (filePaths.cropped_objects && filePaths.cropped_objects.length > 0) {
                    metadataHtml += '<li><strong>Cropped Objects (legacy):</strong><ul>';
                    filePaths.cropped_objects.forEach(path => {
                        metadataHtml += '<li>' + path + '</li>';
                    });
                    metadataHtml += '</ul></li>';
                }
                
                metadataHtml += '</ul>';
            }
            
            // Display grouped detections summary
            if (data.metadata && data.metadata.grouped_detections && Object.keys(data.metadata.grouped_detections).length > 0) {
                metadataHtml += '<h4>Grouped Detections:</h4><ul>';
                for (const [label, info] of Object.entries(data.metadata.grouped_detections)) {
                    const confMin = info.confidence_min !== undefined ? info.confidence_min.toFixed(2) : 'N/A';
                    const confMax = info.confidence_max !== undefined ? info.confidence_max.toFixed(2) : 'N/A';
                    const areaRatio = info.total_mask_area_ratio !== undefined ? info.total_mask_area_ratio + '%' : 'N/A';
                    metadataHtml += '<li><strong>' + label + '</strong>: count=' + info.count + ', area=' + areaRatio + ', conf=[' + confMin + ', ' + confMax + ']</li>';
                }
                metadataHtml += '</ul>';
            }
            
            metadataDisplay.innerHTML = metadataHtml;
            resultArea.style.display = 'block';
        } else {
            throw new Error(data.detail || 'Processing failed');
        }
    } catch (error) {
        alert(`Error: ${error.message}`);
        if (error.message.includes('Model failed to load')) {
            await checkModelStatus();
        }
    } finally {
        processBtn.disabled = false;
        processBtn.textContent = 'Process Image';
    }
}

// Function to set any checkbox state by element ID - can be called multiple times safely
function setCheckboxStateById(elementId, value) {
    const checkbox = document.getElementById(elementId);
    if (checkbox) {
        const boolValue = Boolean(value);
        if (checkbox.checked !== boolValue) {
            checkbox.checked = boolValue;
            console.log(elementId + ' checkbox state set to:', boolValue);
        }
        return true;
    }
    return false;
}

// Try to set checkbox states immediately (before DOMContentLoaded)
(function trySetCheckboxImmediate() {
    const saved = localStorage.getItem(CONFIG_STORAGE_KEY);
    if (saved) {
        try {
            const config = JSON.parse(saved);
            const checkboxesToSet = [
                { id: 'save-segments-separately', key: 'saveSegmentsSeparately' },
                { id: 'save-combined-mask-per-label', key: 'saveCombinedMaskPerLabel' },
                { id: 'save-all-combined-mask', key: 'saveAllCombinedMask' },
                { id: 'show-bounding-box-labels', key: 'showBoundingBoxLabels' },
                { id: 'corner-annotation-enabled', key: 'cornerAnnotationEnabled' }
            ];
            
            let allSet = true;
            for (const cb of checkboxesToSet) {
                if (config[cb.key] !== undefined) {
                    if (!setCheckboxStateById(cb.id, config[cb.key])) {
                        allSet = false;
                    }
                }
            }
            
            if (!allSet) {
                setTimeout(trySetCheckboxImmediate, 10);
            } else {
                console.log('All checkbox states set immediately from localStorage');
            }
        } catch (e) {
            console.error('Error parsing localStorage in immediate load:', e);
        }
    }
})();

// Event listeners
// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    // Set up event listeners after DOM is ready
    if (downloadModelBtn) {
        downloadModelBtn.addEventListener('click', downloadModel);
    }
    if (redownloadModelBtn) {
        redownloadModelBtn.addEventListener('click', showRedownloadToken);
    }
    if (processBtn) {
        processBtn.addEventListener('click', processImage);
    }
    if (saveConfigBtn) {
        saveConfigBtn.addEventListener('click', saveConfiguration);
    } else {
        console.error('Save Configuration button not found. Please refresh the page.');
    }
    
    checkModelStatus();
    
    // Load from localStorage immediately (DOM is now ready)
    loadSavedConfig();
    
    // Then load from API (source of truth) and update
    loadConfigFromAPI().then((config) => {
        // Ensure checkbox state is set from API response (API is source of truth)
        if (config) {
            if (config.save_segments_separately !== undefined) {
                setCheckboxStateById('save-segments-separately', config.save_segments_separately);
            }
            if (config.save_combined_mask_per_label !== undefined) {
                setCheckboxStateById('save-combined-mask-per-label', config.save_combined_mask_per_label);
            }
            if (config.save_all_combined_mask !== undefined) {
                setCheckboxStateById('save-all-combined-mask', config.save_all_combined_mask);
            }
            if (config.show_bounding_box_labels !== undefined) {
                setCheckboxStateById('show-bounding-box-labels', config.show_bounding_box_labels);
            }
            if (config.corner_annotation_enabled !== undefined) {
                setCheckboxStateById('corner-annotation-enabled', config.corner_annotation_enabled);
            }
        }
        setupAutoSave(); // Setup auto-save for checkbox changes after config is loaded
        
        // Final verification after a short delay to ensure state is correct
        setTimeout(() => {
            // Verify checkbox matches API config
            if (config) {
                if (config.save_segments_separately !== undefined) {
                    setCheckboxStateById('save-segments-separately', config.save_segments_separately);
                }
                if (config.save_combined_mask_per_label !== undefined) {
                    setCheckboxStateById('save-combined-mask-per-label', config.save_combined_mask_per_label);
                }
                if (config.save_all_combined_mask !== undefined) {
                    setCheckboxStateById('save-all-combined-mask', config.save_all_combined_mask);
                }
                if (config.show_bounding_box_labels !== undefined) {
                    setCheckboxStateById('show-bounding-box-labels', config.show_bounding_box_labels);
                }
                if (config.corner_annotation_enabled !== undefined) {
                    setCheckboxStateById('corner-annotation-enabled', config.corner_annotation_enabled);
                }
            }
            // Also verify against localStorage
            const saved = localStorage.getItem(CONFIG_STORAGE_KEY);
            if (saved) {
                try {
                    const savedConfig = JSON.parse(saved);
                    const checkboxesToSet = [
                        { id: 'save-segments-separately', key: 'saveSegmentsSeparately' },
                        { id: 'save-combined-mask-per-label', key: 'saveCombinedMaskPerLabel' },
                        { id: 'save-all-combined-mask', key: 'saveAllCombinedMask' },
                        { id: 'show-bounding-box-labels', key: 'showBoundingBoxLabels' },
                        { id: 'corner-annotation-enabled', key: 'cornerAnnotationEnabled' }
                    ];
                    for (const cb of checkboxesToSet) {
                        if (savedConfig[cb.key] !== undefined) {
                            setCheckboxStateById(cb.id, savedConfig[cb.key]);
                        }
                    }
                } catch (e) {
                    console.error('Error in final verification:', e);
                }
            }
        }, 300);
    }).catch((error) => {
        console.error('Error loading config from API:', error);
        // If API fails, rely on localStorage
        setTimeout(() => {
            loadSavedConfig();
        }, 100);
        setupAutoSave(); // Setup auto-save even if config loading fails
    });
});
