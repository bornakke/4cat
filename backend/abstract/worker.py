"""
Worker class that all workers should implement
"""
import traceback
import threading
import time
import abc

from backend.lib.queue import JobQueue
from backend.lib.database import Database
from backend.lib.exceptions import WorkerInterruptedException


class BasicWorker(threading.Thread, metaclass=abc.ABCMeta):
	"""
	Abstract Worker class

	This runs as a separate thread in which a worker method is executed. The
	work method can do whatever the worker needs to do - that part is to be
	implemented by a child class. This class provides scaffolding that makes
	sure crashes are caught properly and the relevant data is available to the
	worker code.
	"""
	type = "misc"  # this should match the job type as saved in the database
	jobdata = {}
	pause = 1  # time to wait between scrapes
	max_workers = 1  # max amount of workers of this type

	queue = None
	job = None
	log = None
	manager = None
	interrupted = False
	modules = None
	loop_time = 0

	def __init__(self, logger, job, db=None, queue=None, manager=None, modules=None):
		"""
		Basic init, just make sure our thread name is meaningful

		:param Database db:  Database connection - if not given, a new one will be created
		:param JobQueue queue: Job Queue - if not given, a new one will be instantiated
		:param WorkerManager manager:  Worker manager reference
		"""
		super().__init__()
		self.name = self.type
		self.log = logger
		self.manager = manager
		self.job = job
		self.loop_time = int(time.time())

		# all_modules cannot be easily imported into a worker because all_modules itself
		# imports all workers, so you get a recursive import that Python (rightly) blocks
		# so for workers, all_modules' content is passed as a constructor argument
		self.all_modules = modules

		self.db = Database(logger=self.log, appname=self.type) if not db else db
		self.queue = JobQueue(logger=self.log, database=self.db) if not queue else queue

	def run(self):
		"""
		Loop the worker

		This simply calls the work method
		"""
		try:
			self.work()
		except WorkerInterruptedException:
			self.log.info("Worker %s interrupted - cancelling." % self.type)
			self.abort()
		except Exception as e:
			frames = traceback.extract_tb(e.__traceback__)
			frames = [frame.filename.split("/").pop() + ":" + str(frame.lineno) for frame in frames]
			location = "->".join(frames)
			self.log.error("Worker %s raised exception %s and will abort: %s at %s" % (self.type, e.__class__.__name__, str(e).replace("\n", ""), location))
			self.job.add_status("Crash during execution")

	def abort(self):
		"""
		Called when the application shuts down

		Can be used to stop loops, for looping workers.
		"""
		pass

	def request_abort(self):
		"""
		Set the 'abort requested' flag

		Child workers should quit at their earliest convenience when this is set

		:return:
		"""
		self.interrupted = True

	@abc.abstractmethod
	def work(self):
		"""
		This is where the actual work happens

		Whatever the worker is supposed to do, it should happen (or be initiated from) this
		method, which is looped indefinitely until the worker is told to finish.
		"""
		pass
