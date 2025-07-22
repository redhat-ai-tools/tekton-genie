package main

import (
	"context"
	"fmt"
	"os"

	v1 "github.com/tektoncd/pipeline/pkg/apis/pipeline/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	"k8s.io/apimachinery/pkg/runtime/serializer/json"
)

func ensureName(meta *metav1.ObjectMeta) {
	if meta.Name == "" && meta.GenerateName != "" {
		meta.Name = meta.GenerateName + "dummy"
	}
}

func main() {
	if len(os.Args) != 2 {
		fmt.Println("Usage: tekton-validate <pipeline_or_pipelinerun.yaml>")
		os.Exit(1)
	}
	filename := os.Args[1]

	data, err := os.ReadFile(filename)
	if err != nil {
		fmt.Fprintf(os.Stderr, "❌ Error reading file: %v\n", err)
		os.Exit(1)
	}

	scheme := runtime.NewScheme()
	if err := v1.AddToScheme(scheme); err != nil {
		fmt.Fprintf(os.Stderr, "❌ Failed to add Tekton v1 scheme: %v\n", err)
		os.Exit(1)
	}

	decoder := json.NewSerializerWithOptions(
		json.DefaultMetaFactory,
		scheme,
		scheme,
		json.SerializerOptions{Yaml: true, Pretty: false, Strict: true},
	)

	obj, gvk, err := decoder.Decode(data, nil, nil)
	if err != nil {
		fmt.Fprintf(os.Stderr, "❌ YAML decode error: %v\n", err)
		os.Exit(1)
	}

	ctx := context.Background()

	switch typed := obj.(type) {
	case *v1.Pipeline:
		ensureName(&typed.ObjectMeta)
		if err := typed.Validate(ctx); err != nil {
			fmt.Fprintf(os.Stderr, "❌ Pipeline validation failed: %v\n", err)
			os.Exit(1)
		}
		fmt.Println("✅ Pipeline is valid.")
	case *v1.PipelineRun:
		ensureName(&typed.ObjectMeta)
		if err := typed.Validate(ctx); err != nil {
			fmt.Fprintf(os.Stderr, "❌ PipelineRun validation failed: %v\n", err)
			os.Exit(1)
		}
		fmt.Println("✅ PipelineRun is valid.")
	default:
		fmt.Fprintf(os.Stderr, "❌ Unsupported Kind: %s\n", gvk.Kind)
		os.Exit(1)
	}
}
