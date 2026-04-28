# uv and venv usage
## Activate the venv
```
source ../my-uv-envs/avird-2026-eda/.venv/Scripts/activate          # bash
# or: ..\my-uv-envs\avird-2026-eda\.venv\Scripts\activate.bat       # cmd
# or: ..\my-uv-envs\avird-2026-eda\.venv\Scripts\Activate.ps1       # PowerShell
```
## Update the env
* Update requirments.txt in the envs directory.  optionally can clear the env.
* be inside the env folder or point to the path of the requirements.txt
```
uv pip install -r requirements.txt
```
## clearing the env
* From the avird-2026-eda directory
```
uv venv --python 3.14 --clear --prompt avird-2026-eda
```