# Clean Install Test for super with brain

> **Automated script:** [`clean_install_with_brain.sh`](./clean_install_with_brain.sh)  
> Run it from the `weroad_brain` project root.

## Manual Steps

1. **Commit, merge and push**
   - `src/github/smnbss/brain`
   - `src/github/smnbss/super`

2. **Wait** for the merge to complete, then pull the latest changes to your local repository.

3. **In the current project**, delete the following folders: `.agents`, `.super`, `.kimi`, `.codex`, `.claude`, `.gemini`

4. **Delete** `~/.super`

5. **Clone** super: `git clone https://github.com/smnbss/super ~/.super`

6. **Run** `super install`, and check that everything is there.

7. **For each CLI** (`super kimi`, `super codex`, `super claude`, `super gemini`), check that they are working properly and that all the necessary files and dependencies are in place.

8. **Check** that the agents are properly installed and configured.

9. **Check** that no duplicated skills are configured.

10. **Report** any anomalies or issues encountered during the installation process.