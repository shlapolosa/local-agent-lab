#!/usr/bin/env bash
# Provision an Oracle Cloud Always-Free ARM VM in me-abudhabi-1 for the lab substrate.
# Idempotent-ish: reuses network resources found by display name. Writes OCIDs + the public IP
# to .lab/oci_ids.env. cloud-init installs Docker + clones the repo + opens the host firewall;
# secrets (.env) are scp'd separately (never in instance metadata).
#   Usage: set -a && source .env && set +a && OCI=.venv/bin/oci bash deploy/oci_provision.sh
set -euo pipefail
OCI="${OCI:-.venv/bin/oci}"
C="$OCI_TENANCY_OCID"                       # root compartment (free-tier tenancy)
AD="fSDo:ME-ABUDHABI-1-AD-1"
IMAGE="ocid1.image.oc1.me-abudhabi-1.aaaaaaaaona5ku66ca3egw2tacfp7znp32kirud4gn7p7gwlcqfq46j26psq"
PUBKEY="$(cat .lab/oracle_vm.pub)"
mkdir -p .lab; : > .lab/oci_ids.env
say() { echo "  $*"; }
q() { "$OCI" "$@"; }

find_by_name() {  # $1 resource(list subcmd words...) --display-name match via jq-less query
  :
}

echo "== VCN =="
VCN=$(q network vcn list -c "$C" --query "data[?\"display-name\"=='lab-vcn'].id | [0]" --raw-output 2>/dev/null || true)
if [ -z "$VCN" ] || [ "$VCN" = "null" ]; then
  VCN=$(q network vcn create -c "$C" --cidr-block 10.0.0.0/16 --display-name lab-vcn --dns-label labvcn \
        --wait-for-state AVAILABLE --query 'data.id' --raw-output)
fi
say "vcn=$VCN"; echo "VCN=$VCN" >> .lab/oci_ids.env

echo "== Internet Gateway =="
IGW=$(q network internet-gateway list -c "$C" --vcn-id "$VCN" --query "data[0].id" --raw-output 2>/dev/null || true)
if [ -z "$IGW" ] || [ "$IGW" = "null" ]; then
  IGW=$(q network internet-gateway create -c "$C" --vcn-id "$VCN" --is-enabled true --display-name lab-igw \
        --wait-for-state AVAILABLE --query 'data.id' --raw-output)
fi
say "igw=$IGW"

echo "== default route table -> 0.0.0.0/0 via IGW =="
RT=$(q network vcn get --vcn-id "$VCN" --query 'data."default-route-table-id"' --raw-output)
q network route-table update --rt-id "$RT" --force \
  --route-rules "[{\"destination\":\"0.0.0.0/0\",\"destinationType\":\"CIDR_BLOCK\",\"networkEntityId\":\"$IGW\"}]" >/dev/null
say "route-table=$RT (0.0.0.0/0 -> IGW)"

echo "== security list (22, 4000, 8501 ingress) =="
SL=$(q network security-list list -c "$C" --vcn-id "$VCN" --query "data[?\"display-name\"=='lab-sl'].id | [0]" --raw-output 2>/dev/null || true)
ING='[{"protocol":"6","source":"0.0.0.0/0","tcpOptions":{"destinationPortRange":{"min":22,"max":22}}},{"protocol":"6","source":"0.0.0.0/0","tcpOptions":{"destinationPortRange":{"min":4000,"max":4000}}},{"protocol":"6","source":"0.0.0.0/0","tcpOptions":{"destinationPortRange":{"min":8501,"max":8501}}}]'
EG='[{"protocol":"all","destination":"0.0.0.0/0"}]'
if [ -z "$SL" ] || [ "$SL" = "null" ]; then
  SL=$(q network security-list create -c "$C" --vcn-id "$VCN" --display-name lab-sl \
        --ingress-security-rules "$ING" --egress-security-rules "$EG" \
        --wait-for-state AVAILABLE --query 'data.id' --raw-output)
fi
say "security-list=$SL"

echo "== public subnet =="
SUBNET=$(q network subnet list -c "$C" --vcn-id "$VCN" --query "data[?\"display-name\"=='lab-subnet'].id | [0]" --raw-output 2>/dev/null || true)
if [ -z "$SUBNET" ] || [ "$SUBNET" = "null" ]; then
  SUBNET=$(q network subnet create -c "$C" --vcn-id "$VCN" --cidr-block 10.0.1.0/24 --display-name lab-subnet \
        --route-table-id "$RT" --security-list-ids "[\"$SL\"]" --dns-label labsub \
        --wait-for-state AVAILABLE --query 'data.id' --raw-output)
fi
say "subnet=$SUBNET"; echo "SUBNET=$SUBNET" >> .lab/oci_ids.env

echo "== cloud-init (install docker + clone repo + open firewall) =="
CLOUDINIT=$(base64 < deploy/oci_cloudinit.sh | tr -d '\n')

echo "== launch instance (A1.Flex 2 OCPU / 12 GB) =="
INST=$(q compute instance list -c "$C" --query "data[?\"display-name\"=='lab-substrate' && \"lifecycle-state\"!='TERMINATED'].id | [0]" --raw-output 2>/dev/null || true)
if [ -z "$INST" ] || [ "$INST" = "null" ]; then
  INST=$(q compute instance launch -c "$C" --availability-domain "$AD" \
        --shape VM.Standard.A1.Flex --shape-config '{"ocpus":2,"memoryInGBs":12}' \
        --image-id "$IMAGE" --subnet-id "$SUBNET" --assign-public-ip true \
        --display-name lab-substrate \
        --metadata "{\"ssh_authorized_keys\":\"$PUBKEY\",\"user_data\":\"$CLOUDINIT\"}" \
        --wait-for-state RUNNING --query 'data.id' --raw-output)
fi
say "instance=$INST"; echo "INSTANCE=$INST" >> .lab/oci_ids.env

echo "== public IP =="
IP=$(q compute instance list-vnics --instance-id "$INST" --query 'data[0]."public-ip"' --raw-output)
say "PUBLIC IP = $IP"; echo "PUBLIC_IP=$IP" >> .lab/oci_ids.env
echo
echo "VM up. Next: ssh -i .lab/oracle_vm ubuntu@$IP  (cloud-init installs Docker; then deploy the substrate)"
