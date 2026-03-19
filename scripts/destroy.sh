#!/usr/bin/env bash
# =============================================================================
# destroy.sh — Destroi TODA a infraestrutura AWS do wiki-rag
#
# Atenção: isso remove EKS, RDS, VPC, ECR, Secrets Manager e IAM roles.
# Use apenas quando terminar a validação do POC.
# =============================================================================
set -euo pipefail

ENVIRONMENT="${ENVIRONMENT:-dev}"
TF_DIR="terraform/environments/${ENVIRONMENT}"

echo "======================================================"
echo " ATENÇÃO: isso vai destruir TODA a infraestrutura"
echo " Ambiente: ${ENVIRONMENT}"
echo "======================================================"
echo ""
read -p "Digite 'destruir' para confirmar: " CONFIRM

if [ "${CONFIRM}" != "destruir" ]; then
  echo "Cancelado."
  exit 0
fi

echo ""
echo "[1/2] Removendo recursos Kubernetes..."
kubectl delete namespace wiki-rag --ignore-not-found=true 2>/dev/null || true

echo ""
echo "[2/2] Executando terraform destroy..."
cd "${TF_DIR}"
terraform destroy -input=false -auto-approve
cd - > /dev/null

echo ""
echo "======================================================"
echo " Infraestrutura destruída. Custo zerado."
echo "======================================================"
