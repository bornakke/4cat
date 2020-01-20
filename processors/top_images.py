"""
Extract most-used images from corpus
"""
import hashlib
import base64

from csv import DictReader

from backend.abstract.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"


class TopImageCounter(BasicProcessor):
	"""
	Top Image listing

	Collects all images used in a data set, and sorts by most-used
	"""
	type = "top-images"  # job type ID
	category = "Post metrics"  # category
	title = "Top images"  # title displayed in UI
	description = "Collect all images used in the data set, and sort by most used. Contains URLs through which the images may potentially be downloaded."  # description displayed in UI
	extension = "csv"  # extension of result file, used internally and in UI
	datasources = ["4chan"]

	input = "csv:image_file, image_md5"
	output = "csv:md5_hash,filename,num_posts,url_4cat,url_4plebs,url_fireden"

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with image hashes, one with the first file name used
		for the image, and one with the amount of times the image was used
		"""
		images = {}

		self.dataset.update_status("Reading source file")
		for post in self.iterate_csv_items(self.source_file):
			if not post["image_file"]:
				continue

			if post["image_md5"] not in images:
				# md5 is stored encoded; make it normal ascii
				md5 = hashlib.md5()
				md5.update(base64.b64decode(post["image_md5"]))

				images[post["image_md5"]] = {
					"filename": post["image_file"],
					"md5": md5.hexdigest(),
					"hash": post["image_md5"],
					"count": 0
				}

			images[post["image_md5"]]["count"] += 1

		top_images = {id: images[id] for id in sorted(images, key=lambda id: images[id]["count"], reverse=True)}

		results = [{
			"md5_hash": images[id]["md5"],
			"filename": images[id]["filename"],
			"num_posts": images[id]["count"],
			"url_4cat": "http://4cat.oilab.nl/api/image/" + images[id]["md5"] + "." + images[id]["filename"].split(".")[
				-1],
			"url_4plebs": "https://archive.4plebs.org/_/search/image/" + images[id]["hash"].replace("/", "_"),
			"url_fireden": "https://boards.fireden.net/_/search/image/" + images[id]["hash"].replace("/", "_")
		} for id in top_images]

		if not results:
			return

		self.write_csv_items_and_finish(results)
