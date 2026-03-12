# Quarto Report

After running the tests, generate a report:

```bash
pytest --vip-report=report/results.json
cd report
quarto render
```

The rendered report can be published to Connect:

```bash
quarto publish connect --server https://connect.example.com
```
