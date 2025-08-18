/// <reference path="../pb_data/types.d.ts" />
migrate((db) => {
  const dao = new Dao(db)
  const collection = dao.findCollectionByNameOrId("sma08jpi5rkoxnh")

  // add
  collection.schema.addField(new SchemaField({
    "system": false,
    "id": "ck1kvq3v",
    "name": "category",
    "type": "text",
    "required": false,
    "presentable": false,
    "unique": false,
    "options": {
      "min": null,
      "max": null,
      "pattern": ""
    }
  }))

  // add
  collection.schema.addField(new SchemaField({
    "system": false,
    "id": "h33ncy2m",
    "name": "within_days",
    "type": "number",
    "required": false,
    "presentable": false,
    "unique": false,
    "options": {
      "min": null,
      "max": null,
      "noDecimal": false
    }
  }))

  return dao.saveCollection(collection)
}, (db) => {
  const dao = new Dao(db)
  const collection = dao.findCollectionByNameOrId("sma08jpi5rkoxnh")

  // remove
  collection.schema.removeField("ck1kvq3v")

  // remove
  collection.schema.removeField("h33ncy2m")

  return dao.saveCollection(collection)
})
