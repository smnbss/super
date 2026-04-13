commit merge and push 
src/github/smnbss/brain
src/github/smnbss/super

wait for the merge to complete, then pull the latest changes to your local repository.

In the current project, delete the following folders: .agents, .super, .kimi, .codex, .claude, .gemini
Then delete ~/.super

git clone https://github.com/smnbss/super ~/.super

Then run super install, and check that everything is there.
Then for each cli (super kimi, super codex, super claude, super gemini), 
check that they are working properly and that all the necessary files and dependencies are in place.
check that the agents are properly installed and configured,
check that no duplicated skills are configured
Finally report any anomalys or issues encountered during the installation process.