/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  const collection = new Collection({
    "id": "xsnma518k27ogrn",
    "created": "2025-08-17 16:29:15.759Z",
    "updated": "2025-08-17 16:29:15.759Z",
    "name": "roleplays",
    "type": "base",
    "system": false,
    "schema": [
      {
        "system": false,
        "id": "q5qibjr9",
        "name": "character",
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
        "id": "wbmieixv",
        "name": "report_type",
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
        "id": "iemizazn",
        "name": "activated",
        "type": "bool",
        "required": false,
        "presentable": false,
        "unique": false,
        "options": {}
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
  const collection = dao.findCollectionByNameOrId("xsnma518k27ogrn");

  return dao.deleteCollection(collection);
})
