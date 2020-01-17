"""
4CAT Web Tool views - pages to be viewed by the user
"""
import os
import re
import csv
import json
import glob
import config
import markdown

from pathlib import Path

import backend

from flask import render_template, jsonify, abort, request, redirect, send_from_directory, flash, get_flashed_messages, \
	url_for
from flask_login import login_required, current_user

from webtool import app, db, log
from webtool.lib.helpers import Pagination, get_preview, error

from webtool.api_tool import delete_dataset, toggle_favourite, queue_processor

from backend.lib.dataset import DataSet
from backend.lib.queue import JobQueue


@app.route("/robots.txt")
def robots():
	with open(os.path.dirname(os.path.abspath(__file__)) + "/static/robots.txt") as robotstxt:
		return robotstxt.read()

@app.route("/access-tokens/")
@login_required
def show_access_tokens():
	user = current_user.get_id()

	if user == "autologin":
		abort(403)

	tokens = db.fetchall("SELECT * FROM access_tokens WHERE name = %s", (user,))

	return render_template("access-tokens.html", tokens=tokens)


@app.route('/')
@login_required
def show_frontpage():
	"""
	Index page: news and introduction

	:return:
	"""

	# load corpus stats that are generated daily, if available
	stats_path = Path(config.PATH_ROOT, "stats.json")
	if stats_path.exists():
		with stats_path.open() as stats_file:
			stats = stats_file.read()
		try:
			stats = json.loads(stats)
		except json.JSONDecodeError:
			stats = None
	else:
		stats = None

	return render_template("frontpage.html", stats=stats, datasources=config.DATASOURCES)


@app.route('/create-dataset/')
@login_required
def show_index():
	"""
	Main tool frontend
	"""
	return render_template('create-dataset.html', datasources=backend.all_modules.datasources)


@app.route('/get-boards/<string:datasource>/')
@login_required
def getboards(datasource):
	if datasource not in config.DATASOURCES or "boards" not in config.DATASOURCES[datasource]:
		result = False
	else:
		result = config.DATASOURCES[datasource]["boards"]

	return jsonify(result)


@app.route('/page/<string:page>/')
def show_page(page):
	"""
	Display a markdown page within the 4CAT UI

	To make adding static pages easier, they may be saved as markdown files
	in the pages subdirectory, and then called via this view. The markdown
	will be parsed to HTML and displayed within the layout template.

	:param page: ID of the page to load, should correspond to a markdown file
	in the pages/ folder (without the .md extension)
	:return:  Rendered template
	"""
	page = re.sub(r"[^a-zA-Z0-9-_]*", "", page)
	page_class = "page-" + page
	page_folder = os.path.dirname(os.path.abspath(__file__)) + "/pages"
	page_path = page_folder + "/" + page + ".md"

	if not os.path.exists(page_path):
		abort(404)

	with open(page_path) as file:
		page_raw = file.read()
		page_parsed = markdown.markdown(page_raw)
		page_parsed = re.sub(r"<h2>(.*)</h2>", r"<h2><span>\1</span></h2>", page_parsed)

	return render_template("page.html", body_content=page_parsed, body_class=page_class, page_name=page)


@app.route('/result/<string:query_file>/')
@login_required
def get_result(query_file):
	"""
	Get dataset result file

	:param str query_file:  name of the result file
	:return:  Result file
	:rmime: text/csv
	"""
	directory = config.PATH_ROOT + "/" + config.PATH_DATA
	return send_from_directory(directory=directory, filename=query_file)


@app.route('/results/', defaults={'page': 1})
@app.route('/results/page/<int:page>/')
@login_required
def show_results(page):
	"""
	Show results overview

	For each result, available analyses are also displayed.

	:return:  Rendered template
	"""
	page_size = 20
	offset = (page - 1) * page_size

	where = ["key_parent = ''"]
	replacements = []

	query_filter = request.args.get("filter", "")

	depth = request.args.get("depth", "own")
	if depth not in ("own", "favourites", "all"):
		depth = "own"

	if depth == "own":
		where.append("parameters::json->>'user' = %s")
		replacements.append(current_user.get_id())

	if depth == "favourites":
		where.append("key IN ( SELECT key FROM users_favourites WHERE name = %s )")
		replacements.append(current_user.get_id())

	if query_filter:
		where.append("query LIKE %s")
		replacements.append("%" + query_filter + "%")

	where = " AND ".join(where)

	num_datasets = db.fetchone("SELECT COUNT(*) AS num FROM datasets WHERE " + where, tuple(replacements))["num"]
	
	replacements.append(page_size)
	replacements.append(offset)
	datasets = db.fetchall("SELECT key FROM datasets WHERE " + where + " ORDER BY timestamp DESC LIMIT %s OFFSET %s",
						   tuple(replacements))
	
	if not datasets and page != 1:
		abort(404)

	pagination = Pagination(page, page_size, num_datasets)
	filtered = []
	processors = backend.all_modules.processors

	for dataset in datasets:
		filtered.append(DataSet(key=dataset["key"], db=db))

	favourites = [row["key"] for row in
				  db.fetchall("SELECT key FROM users_favourites WHERE name = %s", (current_user.get_id(),))]

	return render_template("results.html", filter={"filter": query_filter}, depth=depth, datasets=filtered,
						   pagination=pagination, favourites=favourites)


@app.route('/results/<string:key>/')
@app.route('/results/<string:key>/processors/')
def show_result(key):
	"""
	Show result page

	The page contains dataset details and a download link, but also shows a list
	of finished and available processors.

	:param key:  Result key
	:return:  Rendered template
	"""
	try:
		dataset = DataSet(key=key, db=db)
	except TypeError:
		abort(404)

	# child datasets are not available via a separate page
	if dataset.key_parent:
		abort(404)

	# load list of processors compatible with this dataset
	is_processor_running = False

	# show preview
	if dataset.is_finished() and dataset.num_rows > 0:
		preview = get_preview(dataset)
	else:
		preview = None

	is_favourite = (db.fetchone("SELECT COUNT(*) AS num FROM users_favourites WHERE name = %s AND key = %s",
								(current_user.get_id(), dataset.key))["num"] > 0)

	# if the datasource is configured for it, this dataset may be deleted at some point
	datasource = dataset.parameters.get("datasource", "")
	if datasource in backend.all_modules.datasources and backend.all_modules.datasources[datasource].get("expire-datasets", None):
		timestamp_expires = dataset.timestamp + int(backend.all_modules.datasources[datasource].get("expire-datasets"))
	else:
		timestamp_expires = None

	# we can either show this view as a separate page or as a bunch of html
	# to be retrieved via XHR
	standalone = "processors" not in request.url
	template = "result.html" if standalone else "result-details.html"
	return render_template(template, preview=preview, dataset=dataset, parent_key=dataset.key, processors=backend.all_modules.processors,
						   is_processor_running=is_processor_running, messages=get_flashed_messages(),
						   is_favourite=is_favourite, timestamp_expires=timestamp_expires)


@app.route("/preview-csv/<string:key>/")
@login_required
def preview_csv(key):
	"""
	Preview a CSV file

	Simply passes the first 25 rows of a dataset's csv result file to the
	template renderer.

	:param str key:  Dataset key
	:return:  HTML preview
	"""
	try:
		dataset = DataSet(key=key, db=db)
	except TypeError:
		return error(404, "Dataset not found.")

	try:
		with dataset.get_results_path().open(encoding="utf-8") as csvfile:
			rows = []
			reader = csv.reader(csvfile)
			while len(rows) < 25:
				try:
					row = next(reader)
					rows.append(row)
				except StopIteration:
					break
	except FileNotFoundError:
		abort(404)

	return render_template("result-csv-preview.html", rows=rows, filename=dataset.get_results_path().name)


@app.route("/result/<string:key>/toggle-favourite/")
@login_required
def toggle_favourite_interactive(key):
	"""
	Toggle dataset 'favourite' status

	Uses code from corresponding API endpoint, but redirects to a normal page
	rather than returning JSON as the API does, so this can be used for
	'normal' links.

	:param str key:  Dataset key
	:return:
	"""
	success = toggle_favourite(key)
	if not success.is_json:
		return success

	if success.json["success"]:
		if success.json["favourite_status"]:
			flash("Dataset added to favourites.")
		else:
			flash("Dataset removed from favourites.")

		return redirect("/results/" + key + "/")
	else:
		return render_template("error.html", message="Error while toggling favourite status for dataset %s." % key)


@app.route("/result/<string:key>/restart/")
@login_required
def restart_dataset(key):
	"""
	Run a dataset's query again

	Deletes all underlying datasets, marks dataset as unfinished, and queues a
	job for it.

	:param str key:  Dataset key
	:return:
	"""
	try:
		dataset = DataSet(key=key, db=db)
	except TypeError:
		return error(404, message="Dataset not found.")

	if current_user.get_id() != dataset.parameters.get("user", "") and not current_user.is_admin:
		return error(403, message="Not allowed.")

	if not dataset.is_finished():
		return render_template("error.html", message="This dataset is not finished yet - you cannot re-run it.")

	if "type" not in dataset.parameters:
		return render_template("error.html",
							   message="This is an older dataset that unfortunately lacks the information necessary to properly restart it.")

	for child in dataset.children:
		child.delete()

	dataset.unfinish()
	queue = JobQueue(logger=log, database=db)
	queue.add_job(jobtype=dataset.parameters["type"], remote_id=dataset.key)

	flash("Dataset queued for re-running.")
	return redirect("/results/" + dataset.key + "/")


@app.route("/result/<string:key>/delete/")
@login_required
def delete_dataset_interactive(key):
	"""
	Delete dataset

	Uses code from corresponding API endpoint, but redirects to a normal page
	rather than returning JSON as the API does, so this can be used for
	'normal' links.

	:param str key:  Dataset key
	:return:
	"""
	success = delete_dataset(key)
	if not success.is_json:
		return success
	else:
		flash("Dataset deleted.")
		return redirect(url_for('show_results'))


@app.route('/results/<string:key>/processors/queue/<string:processor>/', methods=["GET", "POST"])
@login_required
def queue_processor_interactive(key, processor):
	"""
	Queue a new processor

	:param str key:  Key of dataset to queue the processor for
	:param str processor:  ID of the processor to queue
	:return:  Either a redirect, or a JSON status if called asynchronously
	"""
	result = queue_processor(key, processor)

	if not result.is_json:
		return result

	if result.json["status"] == "success":
		return redirect("/results/" + key + "/")
