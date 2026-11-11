SAM3 model cache (HuggingFace layout).

This folder should contain:
  huggingface/hub/models--facebook--sam3/
    blobs/          (model file)
    refs/main       (commit hash)
    snapshots/<commit>/sam3.pt

The app looks for: snapshots/*/sam3.pt

If you have only "blobs" and "refs":
  1. Open refs/main and note the commit hash (e.g. 3c879f39...).
  2. Create folder: snapshots/<that_hash>/
  3. Copy the file from blobs/ (the single file there) to snapshots/<hash>/sam3.pt

Alternatively set HF_TOKEN in .env and the container will download the model on first use.
