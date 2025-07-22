# Tekton Pipeline Validator

A standalone CLI tool written in Go that validates Tekton `v1` `Pipeline` and `PipelineRun` YAML definitions using the official Tekton Go API.

---

## Features

- Supports validation of:
  - `Pipeline` (`kind: Pipeline`)
  - `PipelineRun` (`kind: PipelineRun`)
- Uses official Tekton validation logic (`tektoncd/pipeline`)
- Handles `metadata.generateName` in place of `metadata.name`
- Fast and dependency-free (no cluster connection required)

---

## Prerequisites

- [Go 1.20+](https://golang.org/dl/)
- Git (for cloning)
- (Optional) Docker (for container usage)

---

## Building the Validator

### 1. Clone and build

```bash
git clone https://github.com/yourusername/tekton-validator.git
cd tekton-validator
go mod tidy
go build -o tekton-validate
````

## Usage
```bash
./tekton-validate <path/to/pipeline-or-pipelinerun.yaml>
```
