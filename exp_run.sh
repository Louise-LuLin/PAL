#!/bin/bash
read -p "Enter agent, source, episode, budget: " a s e b
echo
python DQN_ner.py --agent $a --source $s --episode $e --budget $b;
