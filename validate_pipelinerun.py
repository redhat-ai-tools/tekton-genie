#!/usr/bin/env python3
import argparse
import subprocess
import sys
from pathlib import Path
from termcolor import cprint
import yaml

def validate_yaml_syntax(file_path: str) -> bool:
    """Validate basic YAML syntax and structure"""
    try:
        with open(file_path, 'r') as f:
            content = yaml.safe_load(f)
            
        if not isinstance(content, dict):
            cprint("❌ Error: Content is not a valid YAML dictionary", "red")
            return False
            
        if content.get('kind') != 'PipelineRun':
            cprint("❌ Error: YAML is not a PipelineRun resource", "red")
            return False
            
        if 'apiVersion' not in content:
            cprint("❌ Error: Missing apiVersion", "red")
            return False
            
        return True
    except yaml.YAMLError as e:
        cprint(f"❌ Error: Invalid YAML syntax - {str(e)}", "red")
        return False
    except Exception as e:
        cprint(f"❌ Error reading file: {str(e)}", "red")
        return False

def validate_pipelinerun(file_path: str, validator_binary: str) -> bool:
    """Validate PipelineRun using the external validator binary"""
    try:
        # First validate YAML syntax
        if not validate_yaml_syntax(file_path):
            return False
            
        # Run the external validator
        result = subprocess.run(
            [validator_binary, file_path],
            capture_output=True,
            text=True
        )
        
        # Check return code
        if result.returncode != 0:
            cprint("❌ Validation failed:", "red")
            if result.stderr:
                print(result.stderr)
            elif result.stdout:
                print(result.stdout)
            return False
            
        cprint("✅ PipelineRun validation successful!", "green")
        return True
        
    except subprocess.CalledProcessError as e:
        cprint(f"❌ Error running validator: {str(e)}", "red")
        if e.stderr:
            print(e.stderr)
        return False
    except Exception as e:
        cprint(f"❌ Error: {str(e)}", "red")
        return False

def main():
    parser = argparse.ArgumentParser(description='Validate a Tekton PipelineRun')
    parser.add_argument('file', help='Path to the PipelineRun YAML file')
    parser.add_argument('--validator', default='tekton-validate',
                      help='Path to the validator binary (default: tekton-validate)')
    
    args = parser.parse_args()
    
    # Check if file exists
    if not Path(args.file).is_file():
        cprint(f"❌ Error: File not found: {args.file}", "red")
        sys.exit(1)
    
    # Check if validator exists and is executable
    if not Path(args.validator).is_file():
        cprint(f"❌ Error: Validator binary not found: {args.validator}", "red")
        sys.exit(1)
    
    # Run validation
    success = validate_pipelinerun(args.file, args.validator)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main() 