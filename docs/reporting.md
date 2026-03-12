# Quarto Report

After running the tests, generate a report:

```bash
pytest
cd report
quarto render
```

The rendered report can be published to Connect:

```bash
quarto publish connect --server https://connect.example.com
```
