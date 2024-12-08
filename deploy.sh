#!/bin/bash

# Default values
NAMESPACE="trading"
IMAGE_TAG=${IMAGE_TAG:-"latest"}
REGISTRY_HOST=${REGISTRY_HOST:-"registry.local"}
REGISTRY_PORT=${REGISTRY_PORT:-"5001"}
IMAGE_NAME="kafka-timescale-ingestor"
FULL_IMAGE_NAME="${REGISTRY_HOST}:${REGISTRY_PORT}/${IMAGE_NAME}"

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Help function
show_help() {
    echo "Usage: ./deploy.sh [options]"
    echo
    echo "Options:"
    echo "  -n, --namespace     Kubernetes namespace [default: trading]"
    echo "  -v, --version      Image version/tag [default: latest]"
    echo "  -h, --help         Show this help message"
}

verify_prerequisites() {
    echo -e "${YELLOW}Verifying prerequisites...${NC}"
    
    # Check if namespace exists
    if ! kubectl get namespace $NAMESPACE >/dev/null 2>&1; then
        echo -e "${RED}Error: Namespace '$NAMESPACE' does not exist${NC}"
        exit 1
    fi
    
    # Check if required secrets exist
    if ! kubectl get secret timescaledb-service-secrets -n $NAMESPACE >/dev/null 2>&1; then
        echo -e "${RED}Error: Secret 'timescaledb-service-secrets' not found in namespace '$NAMESPACE'${NC}"
        exit 1
    fi
    
    # Check if registry secret exists
    if ! kubectl get secret local-registry-cred -n $NAMESPACE >/dev/null 2>&1; then
        echo -e "${RED}Error: Secret 'local-registry-cred' not found in namespace '$NAMESPACE'${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}Prerequisites verified successfully${NC}"
}

verify_registry_connection() {
    echo -e "${YELLOW}Verifying registry connection...${NC}"
    if ! curl -k -s "https://${REGISTRY_HOST}:${REGISTRY_PORT}/v2/_catalog" > /dev/null; then
        echo -e "${RED}Cannot access registry at ${REGISTRY_HOST}:${REGISTRY_PORT}${NC}"
        exit 1
    fi
    echo -e "${GREEN}Registry connection successful${NC}"
}

deploy_app() {
    echo -e "${YELLOW}Deploying application...${NC}"
    
    # Update the image and tag in the kustomization file
    sed -i "s|newName: .*|newName: ${FULL_IMAGE_NAME}|" kubernetes/kustomization.yaml
    sed -i "s|newTag: .*|newTag: ${IMAGE_TAG}|" kubernetes/kustomization.yaml
    
    # Apply kustomization
    if ! kubectl apply -k kubernetes/ -n $NAMESPACE; then
        echo -e "${RED}Failed to apply kustomization${NC}"
        exit 1
    fi
}

verify_deployment() {
    echo -e "${YELLOW}Verifying deployment...${NC}"
    
    if ! kubectl wait --for=condition=available deployment/kafka-timescale-ingestor -n $NAMESPACE --timeout=60s; then
        echo -e "${RED}Error: Deployment not ready${NC}"
        kubectl get pods -n $NAMESPACE
        kubectl describe deployment kafka-timescale-ingestor -n $NAMESPACE
        exit 1
    fi
    
    POD_NAME=$(kubectl get pods -n $NAMESPACE -l app=kafka-timescale-ingestor -o jsonpath="{.items[0].metadata.name}")
    if [ -n "$POD_NAME" ]; then
        echo "Waiting for pod health check..."
        sleep 10
        if ! kubectl exec $POD_NAME -n $NAMESPACE -- curl -s http://localhost:8000/health; then
            echo -e "${RED}Error: Health check failed${NC}"
            kubectl logs $POD_NAME -n $NAMESPACE
            exit 1
        fi
    else
        echo -e "${RED}Error: No pods found${NC}"
        exit 1
    fi
    
    echo -e "${GREEN}Deployment verified successfully${NC}"
}

verify_image() {
    echo -e "${YELLOW}Verifying image accessibility...${NC}"
    local image_url="${FULL_IMAGE_NAME}:${IMAGE_TAG}"
    
    # Try to pull the image locally first
    if ! docker pull $image_url; then
        echo -e "${RED}Failed to pull image: $image_url${NC}"
        echo -e "${YELLOW}Checking if image exists in registry...${NC}"
        
        # Check if image exists in registry
        if curl -k -s "https://${REGISTRY_HOST}:${REGISTRY_PORT}/v2/${IMAGE_NAME}/tags/list" | grep -q "\"${IMAGE_TAG}\""; then
            echo -e "${YELLOW}Image exists in registry but cannot be pulled. Check registry credentials and network policy.${NC}"
        else
            echo -e "${RED}Image $image_url not found in registry${NC}"
        fi
        exit 1
    fi
    echo -e "${GREEN}Image verification successful${NC}"
}

main() {
    # Parse command line arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            -n|--namespace)
                NAMESPACE="$2"
                shift 2
                ;;
            -v|--version)
                IMAGE_TAG="$2"
                shift 2
                ;;
            -h|--help)
                show_help
                exit 0
                ;;
            *)
                echo -e "${RED}Unknown option: $1${NC}"
                show_help
                exit 1
                ;;
        esac
    done
    
    echo "Namespace: $NAMESPACE"
    echo "Image tag: $IMAGE_TAG"
    
    verify_prerequisites
    verify_registry_connection
    verify_image
    deploy_app
    verify_deployment
    
    echo -e "${GREEN}Deployment completed successfully${NC}"
}

# Run main function
main "$@" 