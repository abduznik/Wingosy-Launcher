import hashlib
import os
import zipfile
from pathlib import Path

def calculate_file_hash(file_path):
    if not os.path.exists(file_path):
        return None
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def calculate_folder_hash(folder_path):
    """
    Matches RomM/Wingosy logic: sorted list of 'name:md5' lines.
    """
    if not os.path.exists(folder_path):
        return None
    
    files_data = []
    for root, _, files in os.walk(folder_path):
        for file in files:
            full_path = Path(root) / file
            rel_path = full_path.relative_to(folder_path).as_posix()
            
            md5_hash = hashlib.md5()
            with open(full_path, "rb") as f:
                for byte_block in iter(lambda: f.read(4096), b""):
                    md5_hash.update(byte_block)
            
            files_data.append(f"{rel_path}:{md5_hash.hexdigest()}")
    
    files_data.sort()
    combined = "\n".join(files_data).encode('utf-8')
    return hashlib.sha256(combined).hexdigest()

def calculate_zip_content_hash(zip_path):
    """
    Simulate folder hash for a ZIP by hashing its internal members.
    """
    if not os.path.exists(zip_path) or not zipfile.is_zipfile(zip_path):
        return None
        
    files_data = []
    with zipfile.ZipFile(zip_path, 'r') as z:
        for member in z.infolist():
            if not member.is_dir():
                content = z.read(member)
                md5_h = hashlib.md5(content).hexdigest()
                files_data.append(f"{member.filename}:{md5_h}")
                
    files_data.sort()
    combined = "\n".join(files_data).encode('utf-8')
    return hashlib.sha256(combined).hexdigest()

def zip_path(source_path, output_zip):
    source = Path(source_path)
    with zipfile.ZipFile(output_zip, 'w', zipfile.ZIP_DEFLATED) as zf:
        if source.is_dir():
            for file in source.rglob('*'):
                if file.is_file():
                    zf.write(file, source.name / file.relative_to(source))
        else:
            zf.write(source, source.name)

def read_retroarch_cfg(cfg_path):
    """
    Parse a retroarch.cfg file into a dict.
    Returns {} if file doesn't exist or can't be read.
    Lines look like: key = "value" or key = value
    """
    result = {}
    try:
        with open(cfg_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                if '=' not in line:
                    continue
                key, _, val = line.partition('=')
                key = key.strip()
                val = val.strip().strip('"')
                result[key] = val
    except Exception:
        pass
    return result

def write_retroarch_cfg_values(cfg_path, updates: dict):
    """
    Write key=value pairs into an existing retroarch.cfg.
    Updates existing keys in-place, appends new ones at end.
    Preserves all other lines exactly.
    Returns True on success, False on failure.
    """
    try:
        cfg_path = Path(cfg_path)
        if cfg_path.exists():
            lines = cfg_path.read_text(encoding='utf-8').splitlines()
        else:
            lines = []

        updated_keys = set()
        new_lines = []
        for line in lines:
            stripped = line.strip()
            if '=' in stripped and not stripped.startswith('#'):
                key = stripped.partition('=')[0].strip()
                if key in updates:
                    new_lines.append(f'{key} = "{updates[key]}"')
                    updated_keys.add(key)
                    continue
            new_lines.append(line)

        # Append any keys that weren't already in the file
        for key, val in updates.items():
            if key not in updated_keys:
                new_lines.append(f'{key} = "{val}"')

        cfg_path.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
        return True
    except Exception as e:
        print(f"[retroarch_cfg] Failed to write {cfg_path}: {e}")
        return False
