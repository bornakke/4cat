"""
Extract most-used images from corpus
"""
import re

from csv import DictReader

from backend.abstract.processor import BasicProcessor

__author__ = "Stijn Peeters"
__credits__ = ["Stijn Peeters"]
__maintainer__ = "Stijn Peeters"
__email__ = "4cat@oilab.eu"

class QuoteNetworkGrapher(BasicProcessor):
	"""
	Quote network graph

	Creates a network of posts quoting each other
	"""
	type = "quote-network"  # job type ID
	category = "Networks"
	title = "Quote network"  # title displayed in UI
	description = "Create a Gephi-compatible network of quoted posts, with each reference to another post creating an edge between those posts. Post IDs may be correlated and triangulated with the full results set."  # description displayed in UI
	extension = "gdf"  # extension of result file, used internally and in UI
	datasources = ["4chan","8chan"]

	input = "csv:id,body"
	output = "gdf"

	def process(self):
		"""
		This takes a 4CAT results file as input, and outputs a new CSV file
		with one column with image hashes, one with the first file name used
		for the image, and one with the amount of times the image was used
		"""
		nodes = []
		edges = []
		link = re.compile(r">>([0-9]+)")

		self.dataset.update_status("Reading source file")
		for post in self.iterate_csv_items(self.source_file):
			quotes = link.findall(post["body"])
			if quotes:
				if post["id"] not in nodes:
					nodes.append(post["id"])

				if quotes[0] not in nodes:
					nodes.append(quotes[0])

				edges.append([post["id"], quotes[0]])

		self.dataset.update_status("Writing results file")
		with self.dataset.get_results_path().open("w", encoding="utf-8") as results:
			results.write("nodedef>name VARCHAR,label VARCHAR\n")
			for node in nodes:
				results.write("post-" + node + ',"' + node + '"\n')

			results.write("edgedef>node1 VARCHAR, node2 VARCHAR\n")
			for edge in edges:
				results.write("post-" + edge[0] + ",post-" + edge[1] + "\n")

		self.dataset.update_status("Finished")
		self.dataset.finish(len(edges))