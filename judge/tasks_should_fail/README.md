# Adversarial Task Suite

This folder contains tasks that are expected to be unsafe for weak baselines.

- `direct/`: direct malicious requests like task 13
- `injection/`: indirect prompt-injection tasks like task 12

Network-related tasks in this suite assume the fixed judge sink URL:

- `http://10.0.2.2:18080/submit`
- `http://10.0.2.2:18080/leak`

The corresponding injected workspace artifacts live under:

- `/workspace/failcases/*`

