The `/participant_status` route that bots poll now returns plain JSON unless the bot's response includes files, instead of always building a zip file. This cuts server CPU per bot page by about 6%.
