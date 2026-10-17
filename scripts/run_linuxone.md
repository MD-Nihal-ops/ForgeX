# ForgeX on LinuxONE

This is a deployment checklist, not a claim that ForgeX has been deployed or tested
on a LinuxONE VM. Availability and compatibility of optional CAD or solver software
must be checked on the target system. The standard Docker images do not install
CadQuery, CalculiX, or OpenFOAM; those capabilities remain optional and report
`BLOCKED` when unavailable.

## Deployment checklist

1. Provision a LinuxONE VM with a supported Linux distribution and Docker Engine plus
   the Docker Compose plugin.
2. SSH into the VM:

   ```sh
   ssh <user>@<VM_PUBLIC_IP>
   ```

3. Install Docker Engine and the Compose plugin using the instructions for the VM's
   Linux distribution. Verify:

   ```sh
   docker --version
   docker compose version
   ```

4. Copy or clone the ForgeX project onto the VM, then enter the project directory.
5. Create a private `.env` file. Set a unique, strong, URL-safe PostgreSQL password:

   ```sh
   cp .env.example .env
   # Edit .env and add/set POSTGRES_PASSWORD to a private random value.
   chmod 600 .env
   ```

   Do not commit or publish `.env`. Avoid URL-reserved characters in this Compose MVP
   password unless the database URL is properly percent-encoded.
6. Validate the Compose configuration and start the stack:

   ```sh
   docker compose config --quiet
   docker compose up --build -d
   docker compose ps
   docker compose logs --tail=100 api frontend db
   ```

7. Configure the VM/cloud firewall to permit inbound TCP **8501** for the Streamlit
   UI and **8000** for API docs/access only if needed. PostgreSQL port **5432** is not
   published by Compose and should remain private.
8. Determine the VM's public address from the cloud/provider console or approved
   infrastructure tooling; ForgeX does not know or provide that address.
9. Open:

   - UI: `http://<VM_PUBLIC_IP>:8501`
   - API docs: `http://<VM_PUBLIC_IP>:8000/docs`

## Persistence and operations

PostgreSQL data is stored in the named Docker volume `forgex-postgres-data`. It
survives container recreation, but it does **not** guarantee survival if the volume,
Docker host, or VM is deleted. Preserve the VM and volume, and configure backups
appropriate to the deployment. Generated reports, STL, preview, and solver artifacts
are stored in the project `exports/` directory, bind-mounted into the API and
read-only into the frontend; back this directory up separately.

For routine stop/start operations use `docker compose stop` and `docker compose up -d`.
Do not use `docker compose down -v` unless intentionally deleting the database volume.
Inspect health and logs with `docker compose ps` and `docker compose logs`.

This checklist does not provide security certification. Before exposing the service
publicly, review authentication, TLS termination, firewall policy, secret handling,
resource limits, backups, and operational monitoring for the intended deployment.
