import os
from typing import Dict, Optional
from termcolor import cprint
from llama_stack_client import LlamaStackClient
import yaml
import json
import re
import subprocess
from pathlib import Path
import argparse
import time

# Initialize LlamaStack client
client = LlamaStackClient(base_url="http://localhost:8321")
VECTOR_DB_ID = "tekton_docs_vector_db"

def clean_yaml_response(response: str) -> str:
    """Clean up markdown formatting from YAML response"""
    # Remove markdown code block syntax
    response = re.sub(r'^```ya?ml\s*', '', response, flags=re.MULTILINE)
    response = re.sub(r'\s*```\s*$', '', response, flags=re.MULTILINE)
    
    # Remove any leading/trailing whitespace
    response = response.strip()
    
    return response

def validate_yaml_syntax(content: str) -> bool:
    """Validate basic YAML syntax and structure"""
    try:
        if not isinstance(content, str):
            cprint("❌ Error: Content is not a string", "red")
            return False
            
        pipeline_dict = yaml.safe_load(content)
            
        if not isinstance(pipeline_dict, dict):
            cprint("❌ Error: Content is not a valid YAML dictionary", "red")
            return False
            
        if pipeline_dict.get('kind') != 'PipelineRun':
            cprint("❌ Error: YAML is not a PipelineRun resource", "red")
            return False
            
        if 'apiVersion' not in pipeline_dict:
            cprint("❌ Error: Missing apiVersion", "red")
            return False

        # Check for array-style scripts
        tasks = pipeline_dict.get('spec', {}).get('pipelineSpec', {}).get('tasks', [])
        for task in tasks:
            taskSpec = task.get('taskSpec', {})
            steps = taskSpec.get('steps', [])
            for step in steps:
                if isinstance(step.get('script'), list):
                    cprint("❌ Error: Script field must be a string, not an array", "red")
                    cprint(f"   In step '{step.get('name')}' of task '{task.get('name')}'", "red")
                    return False            
            
        return True
    except yaml.YAMLError as e:
        cprint(f"❌ Error: Invalid YAML syntax - {str(e)}", "red")
        return False
    except Exception as e:
        cprint(f"❌ Error validating YAML: {str(e)}", "red")
        return False

def analyze_and_fix_validation_error(error_message: str, content: str) -> Optional[str]:
    """Analyze validation error and attempt to fix the YAML using the model"""
    try:
        print("\n🔧 Analyzing validation error...")
        
        # Create a prompt for the model to fix the error
        prompt = f"""You are a Tekton expert. Fix the following PipelineRun YAML that has validation errors.

Error message:
{error_message}

Current YAML:
{content}

Rules for fixing Tekton v1 PipelineRun:
1. PipelineRun v1 Required Fields:
   - spec.pipelineSpec: Contains tasks and their definitions
   - spec.params: Array of name/value pairs
   - spec.workspaces: Array of workspace bindings

2. PipelineRun v1 Optional Fields:
   - spec.timeouts: For setting timeouts
   - spec.taskRunTemplate: For common task settings
     including serviceAccountName

3. Common Errors to Fix:
   - Move serviceAccountName under taskRunTemplate
   - Use array for params, not map
   - Use workspaces, not workspaceBindings
   - Use pipelineSpec, not pipelineDefinition
   - Remove any v1beta1 inputs/outputs
   - Remove top-level serviceAccount field

2. Task and Step fields:
   - runAfter goes at task level, not in taskSpec
   - steps (not step) for defining task steps
   - params at task level for passing values
   - workspaces at task level for binding
   - script must be a string or heredoc, not an array
   Example of valid script formats:
     steps:
       - name: test
         script: go test ./...  # Single line
       - name: build
         script: |              # Multi-line
           go build
           ./run-tests.sh

3. Step-level fields:
   - securityContext goes inside individual steps
   - For buildah/privileged containers, use this structure:
       name: build
       image: quay.io/buildah/buildah
       script: |
         buildah bud --storage-driver=vfs -t $(params.IMAGE) .
       securityContext:
         privileged: true
         runAsUser: 0

4. Parameter rules:
   - PipelineRun spec.params: ONLY name and value
     Example:
     params:
       - name: git-url
         value: "https://github.com/example/repo"
   - PipelineSpec params: MUST have type
     Example:
     params:
       - name: git-url
         type: string
   - TaskSpec params: MUST have type
     Example:
     taskSpec:
       params:
         - name: IMAGE
           type: string
           description: optional description
   - Task params: ONLY name and value for passing
     Example:
     params:
       - name: IMAGE
         value: $(params.image-url)

Workspace configuration notes:
   - Define workspaces at PipelineRun level with emptyDir
   - Reference them in tasks using the workspace field
   - Use consistent workspace names across all levels
   - Ensure proper indentation in the YAML output

Response format: Output ONLY the raw YAML content with no markdown formatting."""

        # Use the chat endpoint to get the fix
        response = client.chat.completions.create(
            model="gemini-2.5-pro",
            messages=[
                {"role": "system", "content": "You are a Tekton expert. Fix invalid YAML."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        
        # Get the fixed YAML from the response
        if hasattr(response, 'choices') and response.choices:
            fixed_yaml = response.choices[0].message.content
        else:
            fixed_yaml = str(response)
        
        if not fixed_yaml:
            print("❌ Empty response from model")
            return None
            
        # Clean up any markdown formatting
        fixed_yaml = clean_yaml_response(fixed_yaml)
        
        # Basic YAML validation
        if not validate_yaml_syntax(fixed_yaml):
            return None
            
        return fixed_yaml
            
    except Exception as e:
        print(f"❌ Error fixing validation error: {e}")
        return None

def validate_with_binary(content: str, validator_binary: str, temp_file: str = "temp_pipeline.yaml") -> bool:
    """Validate PipelineRun using the external validator binary"""
    try:
        # Save content to temporary file
        with open(temp_file, 'w') as f:
            f.write(content)
        
        # Run the external validator
        result = subprocess.run(
            [validator_binary, temp_file],
            capture_output=True,
            text=True
        )
        
        # Clean up temp file
        os.remove(temp_file)
        
        # Check return code
        if result.returncode != 0:
            error_message = result.stderr if result.stderr else result.stdout
            print("❌ External validation failed:")
            print(error_message)
            
            # Try to fix the error
            print("\n🔧 Attempting to fix validation errors...")
            fixed_yaml = analyze_and_fix_validation_error(error_message, content)
            
            if fixed_yaml:
                print("\n📝 Fixed YAML content:")
                print("-" * 40)
                print(fixed_yaml)
                print("-" * 40)
                
                # Ask user if they want to use the fix
                use_fix = input("\nDo you want to use this fix? (y/n): ").lower()
                if use_fix == 'y':
                    print("\n🔍 Validating the fixed PipelineRun...")
                    # Validate the fix
                    with open(temp_file, 'w') as f:
                        f.write(fixed_yaml)
                    
                    validation_result = subprocess.run(
                        [validator_binary, temp_file],
                        capture_output=True,
                        text=True
                    )
                    
                    os.remove(temp_file)
                    
                    if validation_result.returncode == 0:
                        print("✅ Fixed YAML validates successfully!")
                        # Update the content in the original file
                        with open("generated_pipelinerun.yaml", 'w') as f:
                            f.write(fixed_yaml)
                        return True
                    else:
                        print("❌ Fixed YAML still has validation errors:")
                        error_output = validation_result.stderr if validation_result.stderr else validation_result.stdout
                        print(error_output)
                        print("\nPlease check the errors and try again.")
            
            return False
            
        cprint("✅ External validation successful!", "green")
        return True
        
    except subprocess.CalledProcessError as e:
        cprint(f"❌ Error running validator: {str(e)}", "red")
        if e.stderr:
            print(e.stderr)
        return False
    except Exception as e:
        cprint(f"❌ Error: {str(e)}", "red")
        return False
    finally:
        # Ensure temp file is removed
        if os.path.exists(temp_file):
            os.remove(temp_file)

def ingest_to_rag(content: str, filename: str) -> bool:
    """Ingest a validated PipelineRun into the RAG system"""
    try:
        # Prepare the document
        document = {
            "document_id": f"generated_{int(time.time())}",
            "content": content,
            "metadata": {
                "source": filename,
                "type": "generated",
                "uploaded_at": int(time.time())
            }
        }
        
        # Insert into vector database
        client.tool_runtime.rag_tool.insert(
            documents=[document],
            vector_db_id=VECTOR_DB_ID,
            chunk_size_in_tokens=256,
        )
        
        cprint(f"✅ Successfully ingested PipelineRun into RAG system", "green")
        return True
        
    except Exception as e:
        cprint(f"❌ Error ingesting to RAG: {e}", "red")
        return False

def search_knowledge_base(query: str, vector_db_id: str, max_results: int = 3) -> str:
    """Search the vector database for relevant context"""
    try:
        # Query the RAG tool with the correct parameters
        response = client.tool_runtime.rag_tool.query(
            content=query,
            vector_db_ids=[vector_db_id]
        )
        
        # Extract content from response
        if hasattr(response, 'content'):
            # If response has content attribute with text items
            texts = [item.text for item in response.content if hasattr(item, 'text')]
            return "\n---\n".join(texts[:max_results])  # Limit results after getting them
        elif isinstance(response, str):
            # If response is directly a string
            return response
        else:
            # Try to convert response to string
            return str(response)
            
    except Exception as e:
        cprint(f"Error searching knowledge base: {e}", "red")
        return ""

def generate_pipelinerun(requirements: str, context: str) -> Optional[str]:
    """Generate a PipelineRun using Gemini"""
    try:
        prompt = f"""You are a Tekton expert. Generate a valid PipelineRun YAML that exactly matches the requirements.

Requirements:

{requirements}

Here is relevant documentation and examples for reference:
{context}

Rules:
1. Generate ONLY the PipelineRun resource
2. Use valid Tekton v1 syntax
3. Use taskSpec blocks directly in the PipelineRun
4. Follow the exact same syntax as shown in the examples
5. Ensure the YAML starts with apiVersion
6. Do not include any markdown formatting or code block syntax
7. Output ONLY the raw YAML content, no explanations or other text

Response format: Output ONLY the raw YAML content with no markdown formatting."""

        # Use the chat endpoint instead of completions
        response = client.chat.completions.create(
            model="gemini-2.5-pro",
            messages=[
                {"role": "system", "content": "You are a Tekton expert. Generate only valid YAML."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1
        )
        
        # Get the generated YAML from the response
        if hasattr(response, 'choices') and response.choices:
            yaml_content = response.choices[0].message.content
        else:
            yaml_content = str(response)
        
        if not yaml_content:
            cprint("Error: Empty response from model", "red")
            return None
            
        # Clean up any markdown formatting
        yaml_content = clean_yaml_response(yaml_content)
        
        # Basic YAML validation
        if not validate_yaml_syntax(yaml_content):
            return None
            
        return yaml_content
            
    except Exception as e:
        cprint(f"Error generating PipelineRun: {e}", "red")
        return None

def save_yaml(content: str, filename: str = "generated_pipelinerun.yaml") -> bool:
    """Save content to a YAML file"""
    try:
        with open(filename, 'w') as f:
            f.write(content)
        return True
    except Exception as e:
        cprint(f"Error saving file: {e}", "red")
        return False

def main():
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='Generate and validate a Tekton PipelineRun')
    parser.add_argument('--validator', default='tekton-validate',
                      help='Path to the validator binary (default: tekton-validate)')
    parser.add_argument('--no-ingest', action='store_true',
                      help='Skip ingesting successful PipelineRuns back to RAG')
    args = parser.parse_args()
    
    # Check if validator exists
    if not Path(args.validator).is_file():
        cprint(f"❌ Warning: Validator binary not found at {args.validator}. Will skip external validation.", "yellow")
        args.validator = None

    # Your specific requirements
    requirements = """Create a Tekton PipelineRun (ONLY the PipelineRun resource, no separate Task or Pipeline objects) that:
• Clones the repository https://github.com/savitaashture/pac-demo.
• Runs the project's tests.
• Builds an OCI image from a Dockerfile in the repo.
• Pushes the image to a Docker registry whose URL is provided as a param.

Hard requirements:
1. Use taskSpec blocks embedded directly inside the PipelineRun (do not reference external Tasks or Pipelines).
2. Use a single workspace shared across steps.
3. Accept two Params: 'git-url' and 'image-url'.
4. Use catalog images (e.g. alpine/git, golang, buildah) that do not require private pulls.
5. Generate invalid Tekton syntax by:
   - Using incorrect field names (e.g. 'step' instead of 'steps')
   - Placing fields at wrong nesting levels
   - Using non-existent Tekton fields
   - Mixing v1beta1 and v1 syntax
   - Using incorrect parameter references
6. Output must still be valid YAML starting with apiVersion."""

    # Search for relevant documentation
    print("🔍 Searching for relevant Tekton documentation...")
    context = search_knowledge_base(
        query="""Find examples of:
1. PipelineRuns with embedded taskSpec
2. Git clone operations
3. Building and pushing container images
4. Using workspaces across tasks""",
        vector_db_id=VECTOR_DB_ID
    )
    
    if not context:
        print("❌ No relevant documentation found. Please ensure the vector database is populated.")
        return
    
    print("✨ Generating PipelineRun...")
    pipeline_run = generate_pipelinerun(requirements, context)
    
    if pipeline_run:
        print("\n📄 Generated PipelineRun:")
        print("-" * 40)
        print(pipeline_run)
        print("-" * 40)
        
        # Validate with external binary if available
        if args.validator:
            print("\n🔍 Running external validation...")
            if not validate_with_binary(pipeline_run, args.validator):
                print("❌ External validation failed. Please check the errors above.")
                return
        
        save = input("\nDo you want to save this PipelineRun? (y/n): ").lower()
        if save == 'y':
            filename = input("Enter filename (default: generated_pipelinerun.yaml): ").strip()
            if not filename:
                filename = "generated_pipelinerun.yaml"
            
            if save_yaml(pipeline_run, filename):
                print(f"✅ PipelineRun saved to {filename}")
                
                # Ingest successful PipelineRun back to RAG if enabled
                if not args.no_ingest:
                    print("\n📚 Ingesting validated PipelineRun into RAG system...")
                    if ingest_to_rag(pipeline_run, filename):
                        print("✅ PipelineRun ingested successfully")
                    else:
                        print("❌ Failed to ingest PipelineRun")
            else:
                print("❌ Failed to save PipelineRun")
    else:
        print("❌ Failed to generate valid PipelineRun")

if __name__ == "__main__":
    main()
