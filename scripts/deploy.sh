#!/usr/bin/env bash
# =============================================================================
# deploy.sh — Sobe toda a infraestrutura e faz deploy do wiki-rag no EKS
#
# Pré-requisitos:
#   - AWS CLI configurado (aws configure ou IRSA no devcontainer)
#   - Docker rodando
#   - terraform >= 1.6
#   - kubectl instalado
#   - Arquivo terraform/environments/dev/terraform.tfvars preenchido
#
# Uso:
#   chmod +x scripts/deploy.sh
#   ./scripts/deploy.sh
# =============================================================================
set -euo pipefail

AWS_REGION="${AWS_REGION:-us-east-1}"
ENVIRONMENT="${ENVIRONMENT:-dev}"
PROJECT="${PROJECT:-wiki-rag}"
TF_DIR="terraform/environments/${ENVIRONMENT}"

echo "======================================================"
echo " wiki-rag deploy — AWS EKS"
echo " Região: ${AWS_REGION} | Ambiente: ${ENVIRONMENT}"
echo "======================================================"

# ── 1. Terraform apply ────────────────────────────────────────────────────────
echo ""
echo "[1/5] Provisionando infraestrutura com Terraform..."
cd "${TF_DIR}"
terraform init -input=false
terraform apply -input=false -auto-approve
cd - > /dev/null

# ── 2. Captura outputs do Terraform ──────────────────────────────────────────
echo ""
echo "[2/5] Lendo outputs do Terraform..."
CLUSTER_NAME=$(terraform -chdir="${TF_DIR}" output -raw eks_cluster_name)
ECR_URL=$(terraform -chdir="${TF_DIR}" output -raw ecr_repository_url)
ROLE_ARN=$(terraform -chdir="${TF_DIR}" output -raw wiki_rag_role_arn)
SECRET_NAME=$(terraform -chdir="${TF_DIR}" output -raw secret_name)
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

echo "  Cluster : ${CLUSTER_NAME}"
echo "  ECR     : ${ECR_URL}"
echo "  Role ARN: ${ROLE_ARN}"
echo "  Secret  : ${SECRET_NAME}"

# ── 3. Build e push da imagem para ECR ───────────────────────────────────────
echo ""
echo "[3/5] Build e push da imagem Docker para ECR..."
IMAGE_TAG=$(git rev-parse --short HEAD 2>/dev/null || echo "latest")
FULL_IMAGE="${ECR_URL}:${IMAGE_TAG}"

aws ecr get-login-password --region "${AWS_REGION}" \
  | docker login --username AWS --password-stdin "${ECR_URL}"

docker build -t "${FULL_IMAGE}" .
docker push "${FULL_IMAGE}"

# Também tag como latest
docker tag "${FULL_IMAGE}" "${ECR_URL}:latest"
docker push "${ECR_URL}:latest"

echo "  Imagem publicada: ${FULL_IMAGE}"

# ── 4. Configura kubectl ──────────────────────────────────────────────────────
echo ""
echo "[4/5] Configurando kubectl para o cluster ${CLUSTER_NAME}..."
aws eks update-kubeconfig \
  --region "${AWS_REGION}" \
  --name "${CLUSTER_NAME}"

# ── 5. Aplica manifests Kubernetes ───────────────────────────────────────────
echo ""
echo "[5/5] Aplicando manifests Kubernetes..."

# Atualiza valores dinâmicos nos manifests antes de aplicar
sed -i "s|ACCOUNT_ID.dkr.ecr.us-east-1.amazonaws.com/wiki-rag-api:latest|${FULL_IMAGE}|g" k8s/deployment.yaml
sed -i "s|arn:aws:iam::ACCOUNT_ID:role/wiki-rag-dev-wiki-rag|${ROLE_ARN}|g" k8s/serviceaccount.yaml
sed -i "s|wiki-rag-dev/app|${SECRET_NAME}|g" k8s/configmap.yaml

kubectl apply -f k8s/namespace.yaml
kubectl apply -f k8s/serviceaccount.yaml
kubectl apply -f k8s/configmap.yaml
kubectl apply -f k8s/deployment.yaml
kubectl apply -f k8s/service.yaml

echo ""
echo "Aguardando pods ficarem prontos..."
kubectl rollout status deployment/wiki-rag -n wiki-rag --timeout=180s

# ── Resumo ────────────────────────────────────────────────────────────────────
echo ""
echo "======================================================"
echo " Deploy concluído!"
echo ""
echo " Para acessar o app localmente (port-forward):"
echo "   kubectl port-forward svc/wiki-rag 8001:80 -n wiki-rag"
echo "   Abra: http://localhost:8001/ui"
echo ""
echo " Para ver os logs:"
echo "   kubectl logs -f deployment/wiki-rag -n wiki-rag"
echo ""
echo " Para destruir tudo:"
echo "   ./scripts/destroy.sh"
echo "======================================================"
