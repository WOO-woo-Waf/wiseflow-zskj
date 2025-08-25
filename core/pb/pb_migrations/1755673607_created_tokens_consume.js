/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  const collection = new Collection({
    "id": "y02yh19in8bfd23",
    "created": "2025-08-20 07:06:47.134Z",
    "updated": "2025-08-20 07:06:47.134Z",
    "name": "tokens_consume",
    "type": "base",
    "system": false,
    "schema": [
      {
        "system": false,
        "id": "x3qjtgx3",
        "name": "model",
        "type": "text",
        "required": false,
        "presentable": false,
        "unique": false,
        "options": {
          "min": null,
          "max": null,
          "pattern": ""
        }
      },
      {
        "system": false,
        "id": "tc0qfsd4",
        "name": "purpose",
        "type": "text",
        "required": false,
        "presentable": false,
        "unique": false,
        "options": {
          "min": null,
          "max": null,
          "pattern": ""
        }
      },
      {
        "system": false,
        "id": "yzsr9dr2",
        "name": "total_tokens",
        "type": "number",
        "required": false,
        "presentable": false,
        "unique": false,
        "options": {
          "min": null,
          "max": null,
          "noDecimal": false
        }
      }
    ],
    "indexes": [],
    "listRule": null,
    "viewRule": null,
    "createRule": null,
    "updateRule": null,
    "deleteRule": null,
    "options": {}
  });

  return Dao(db).saveCollection(collection);
}, (db) => {
  const dao = new Dao(db);
  const collection = dao.findCollectionByNameOrId("y02yh19in8bfd23");

  return dao.deleteCollection(collection);
})
