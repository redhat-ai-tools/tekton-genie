from llama_stack_client import LlamaStackClient
from typing import List

def extract_text_from_response(response) -> str:
    # response.content is a list of TextContentItem, each with .text attribute
    # We join all text pieces into one string
    texts: List[str] = [item.text for item in response.content if hasattr(item, 'text')]
    return "\n".join(texts)

client = LlamaStackClient(base_url="http://localhost:8321")

content = """
Generate a Tekton pipeline YAML that clones this Go project:
https://github.com/jkhelil/go-helloworld.git

The pipeline should:
- Clone the repository using git-clone task
- Build the Go project using a build step
- Assume it’s running in a Kubernetes cluster

Only return the Tekton YAML.
"""

response = client.tool_runtime.rag_tool.query(
    content=content,
    vector_db_ids=["tekton_docs_vector_db"]
)

print("\n📝 Generated Tekton YAML:\n")
#print(response)
generated_yaml = extract_text_from_response(response)
print("📝 Generated Tekton YAML:\n")
print(generated_yaml)
