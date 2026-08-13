# API Contracts

## General conventions

- Base path: `/api/v1`
- Request and response bodies use JSON.
- Errors use a consistent structure.
- Input validation occurs at the API boundary.
- Pagination is used for large collections.
- Dates and timestamps use ISO 8601.

## Error response

```json
{
    "error": {
        "code": "VALIDATION_ERROR",
        "message": "The request could not be processed.",
        "details": []
    }
}
```
