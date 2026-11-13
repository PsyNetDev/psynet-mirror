# Ensure Redis and Postgres containers exist on the Dallinger Docker network.
# Source this from a local CI runner (do not run it directly).
#
# Dallinger's in-network Docker tests talk to redis://dallinger_redis:6379 and
# postgres on that same user-defined network. This is not the host-port setup
# created by ``psynet services ensure``.
#
# ``set -euo pipefail`` is required even when sourced: otherwise a failed
# ``docker network create`` or ``docker run`` is ignored and the parent runner
# continues into tests without Redis/Postgres.

set -euo pipefail

echo "Checking Docker access..."
if [[ "$(docker network ls | grep "could not be found in this WSL 2 distro")" != "" ]]
then
  echo "Docker installation could not be found in this WSL 2 distro. Did you remember to launch Docker Desktop?"
  exit 1
fi

echo "Confirming that the Dallinger network exists..."
if [[ "$(docker network ls | grep dallinger)" = "" ]]
then
  echo "...no. Creating now..."
  docker network create dallinger
else
  echo "...yes."
fi

echo "Confirming that dallinger_redis is running..."
docker start dallinger_redis || true
if [[ "$(docker ps | grep dallinger_redis)" = "" ]]
then
  echo "...no. Creating now..."
  docker run -d --name dallinger_redis --network=dallinger \
    -v dallinger_redis:/data \
    redis redis-server \
    --appendonly yes
else
  echo "...yes."
fi

echo "Confirming that dallinger_postgres is running..."
# Matches psynet/services.py (a test keeps the image and volume equal).
# PostgreSQL 18 can't open the old container's dallinger_postgres volume, so
# that container is replaced and the volume kept.
postgres_image=postgres:18-trixie
current_image="$(docker container inspect -f '{{.Config.Image}}' dallinger_postgres 2>/dev/null || true)"
if [[ -n "$current_image" && "$current_image" != "$postgres_image" ]]
then
  echo "...replacing it, because it runs $current_image."
  docker rm --force dallinger_postgres
fi
docker start dallinger_postgres || true
if [[ "$(docker ps | grep dallinger_postgres)" = "" ]]
then
  echo "...no. Creating now..."
  docker run -d --name dallinger_postgres --network=dallinger \
  -e POSTGRES_USER=dallinger \
  -e POSTGRES_PASSWORD=dallinger \
  -e POSTGRES_DB=dallinger \
  -v dallinger_postgres18:/var/lib/postgresql \
  "$postgres_image" postgres -c jit=off
else
  echo "...yes."
fi
