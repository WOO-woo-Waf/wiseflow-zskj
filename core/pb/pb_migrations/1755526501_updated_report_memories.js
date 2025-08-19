/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  const dao = new Dao(db)
  const collection = dao.findCollectionByNameOrId("i6y228w7il3bkhw")

  // add
  collection.schema.addField(new SchemaField({
    "system": false,
    "id": "1hhhpgpl",
    "name": "docx",
    "type": "file",
    "required": false,
    "presentable": false,
    "unique": false,
    "options": {
      "mimeTypes": [],
      "thumbs": [],
      "maxSelect": 1,
      "maxSize": 5242880,
      "protected": false
    }
  }))

  return dao.saveCollection(collection)
}, (db) => {
  const dao = new Dao(db)
  const collection = dao.findCollectionByNameOrId("i6y228w7il3bkhw")

  // remove
  collection.schema.removeField("1hhhpgpl")

  return dao.saveCollection(collection)
})
