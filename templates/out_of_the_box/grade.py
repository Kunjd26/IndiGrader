import os
import sys
import argparse
import json
import shutil
import subprocess
import tempfile
import time
import difflib
import resource


# Standardized Flags
# CFLAGS="-Wall"
# CXXFLAGS="-Wall"
# LDFLAGS="-lm -lpthread"
CFLAGS = ["-Wall"]
CXXFLAGS = ["-Wall"]
LDFLAGS = ["-lm", "-lpthread"]


# SUBMISSION=""
# QUESTION=""
# TESTCASES_DIR=""
# SANDBOX=false
# CONFIG_FILE="config.json"
# TARGET_TESTCASE=""
# SAVE_OUTPUT_DIR=""
# Parse arguments
# while [[ "$#" -gt 0 ]]; do
#     case $1 in
#         --submission) SUBMISSION="$2"; shift ;;
#         --question) QUESTION="$2"; shift ;;
#         --testcases_dir) TESTCASES_DIR="$2"; shift ;;
#         --sandbox) SANDBOX=true ;;
#         --config) CONFIG_FILE="$2"; shift ;;
#         -t|--testcase) TARGET_TESTCASE="$2"; shift ;;
#         --save_output_dir) SAVE_OUTPUT_DIR="$2"; shift ;;
#         *) echo "[LOG] Unknown parameter: $1"; exit 1 ;;
#     esac
#     shift
# done
def parse_arguments():
	parser = argparse.ArgumentParser(description="Unified Grader (Python Version)")
	parser.add_argument("--submission", required=True, help="Path to submission file/directory")
	parser.add_argument("--question", required=True, help="Question name/ID")
	parser.add_argument("--testcases_dir", required=True, help="Directory containing testcases")

# if [ -z "$SUBMISSION" ] || [ -z "$QUESTION" ] || [ -z "$TESTCASES_DIR" ]; then
#     echo "[LOG] Missing required arguments: --submission, --question, --testcases_dir"
#     exit 1
# fi

	parser.add_argument("--sandbox", action="store_true", help="Enable sandboxing (uses firejail if available)")
	parser.add_argument("--config", default="config.json", help="Path to configuration file")
	parser.add_argument("-t", "--testcase", default="", help="Target a specific testcase ID")
	parser.add_argument("--save_output_dir", default="", help="Directory to save execution stdout files")
	return parser.parse_args()


def load_config(config_file, question):

	# if [ ! -f "$CONFIG_FILE" ]; then
	# 	echo "[LOG] Config file not found: $CONFIG_FILE"
	# 	exit 1
	# fi

	# # Load config
	# EVALUATOR=$(jq -r ".\"$QUESTION\".evaluator // empty" "$CONFIG_FILE" 2>/dev/null)
	# TIMEOUT_SEC=$(jq -r ".\"$QUESTION\".timeout // 5" "$CONFIG_FILE" 2>/dev/null)
	# MEM_CAP_MB=$(jq -r ".\"$QUESTION\".memory_cap_mb // 512" "$CONFIG_FILE" 2>/dev/null)
	# MAKEFILE_MODE=$(jq -r ".\"$QUESTION\".makefile // false" "$CONFIG_FILE" 2>/dev/null)
	# EXEC_NAME=$(jq -r ".\"$QUESTION\".executable_name // \"$QUESTION\"" "$CONFIG_FILE" 2>/dev/null)


	if not os.path.isfile(config_file):
		print(f"[LOG] Config file not found: {config_file}")
		sys.exit(1)
		
	try:
		with open(config_file, "r") as f:
			config = json.load(f)
	except Exception:
		config = {}

	q_config = config.get(question, {})
	evaluator = q_config.get("evaluator", None)
	timeout_sec = q_config.get("timeout", 5)
	memory_cap_mb = q_config.get("memory_cap_mb", 512)
	makefile_mode = q_config.get("makefile", False)
	exec_name = q_config.get("executable_name", question)
	
	return evaluator, timeout_sec, memory_cap_mb, makefile_mode, exec_name

def strip_leading_zeros(s):
	return s.lstrip('0') if s else ""

def diff_files(actual_path, expected_path):
	"""OS-independent line-by-line comparison ignoring trailing whitespace and blank lines."""
	# TODO This MUST be changed for exact grading equivalence.
	# This only:

	#     removes leading whitespace
	#     removes trailing whitespace
	#     removes completely blank lines

	# It does NOT:

	#     ignore case
	#     ignore internal whitespace

	try:
		with open(actual_path, 'r', encoding='utf-8', errors='ignore') as f1, \
			 open(expected_path, 'r', encoding='utf-8', errors='ignore') as f2:
			
			lines1 = [line.strip() for line in f1 if line.strip()]
			lines2 = [line.strip() for line in f2 if line.strip()]
			
			return lines1 == lines2
	except Exception:
		return False


def print_diff_snippet(actual_path, expected_path):
	"""Fallback cross-platform unified diff snippet generator."""
	try:
		with open(expected_path, 'r', encoding='utf-8', errors='ignore') as f2, \
			 open(actual_path, 'r', encoding='utf-8', errors='ignore') as f1:
			

			diff = difflib.unified_diff(
				f2.readlines(), 
				f1.readlines(), 
				fromfile='Expected',
				tofile='Actual',
				n=3
			)

			for i, line in enumerate(diff):
				if i >= 15:
					break
				print(f"[LOG] {line.rstrip()}")
	except Exception as e:
		print(f"[LOG] Could not generate diff: {e}")




def run_standard(
	executable,
	input_item,
	expected_output,
	sandbox_dir,
	test_name,
	ext,
	timeout_sec,
	memory_cap_mb,
	sandbox_flag,
	testcases_dir,
	question
):
	expected_output = os.path.abspath(expected_output)
	os.makedirs(sandbox_dir, exist_ok=True)
	actual_output = os.path.join(sandbox_dir, "stdout.txt")
	stderr_output = os.path.join(sandbox_dir, "stderr.txt")


	# TODO Problamatic Python copytree() copy hidden files.
	
	# Global Static Injection
	# if [ -d "$TESTCASES_DIR/$QUESTION/static" ]; then
	#     cp -r "$TESTCASES_DIR/$QUESTION/static/"* "$sandbox_dir/" 2>/dev/null || true
	# fi
	q_static_dir = os.path.join(testcases_dir, question, "static")
	if os.path.isdir(q_static_dir):
		for item in os.listdir(q_static_dir):
			s = os.path.join(q_static_dir, item)
			d = os.path.join(sandbox_dir, item)
			if os.path.isdir(s):
				shutil.copytree(s, d, dirs_exist_ok=True)
			else:
				shutil.copy2(s, d)


	# TODO Problamatic Python copytree() copy hidden files.

	# local stdin_file="/dev/null"
	# local args_file="/dev/null"
	stdin_file = None
	args_file = None

	# if [ -d "$input_item" ]; then
	if os.path.isdir(input_item):
		# Directory Mode (Hybrid)
		# cp -r "$input_item/"* "$sandbox_dir/" 2>/dev/null || true
		# if [ -f "$sandbox_dir/stdin.txt" ]; then
		#     stdin_file="$sandbox_dir/stdin.txt"
		# fi
		# if [ -f "$sandbox_dir/args.txt" ]; then
		#     args_file="$sandbox_dir/args.txt"
		# fi
		for item in os.listdir(input_item):
			s = os.path.join(input_item, item)
			d = os.path.join(sandbox_dir, item)
			if os.path.isdir(s):
				shutil.copytree(s, d, dirs_exist_ok=True)
			else:
				shutil.copy2(s, d)
		
		potential_stdin = os.path.join(sandbox_dir, "stdin.txt")
		if os.path.isfile(potential_stdin):
			stdin_file = potential_stdin
			
		potential_args = os.path.join(sandbox_dir, "args.txt")
		if os.path.isfile(potential_args):
			args_file = potential_args

	# elif [[ "$input_item" == *args*.txt ]]; then
	#     # Arg-only Mode
	#     if [[ ! "$input_item" == /* ]]; then
	#         args_file="$PWD/$input_item"
	#     else
	#         args_file="$input_item"
	#     fi	
	elif "args" in os.path.basename(input_item) and input_item.endswith(".txt"):
		# Arg-only Mode
		args_file = os.path.abspath(input_item)

	# else
	#     # Stdin-only Mode
	#     if [[ ! "$input_item" == /* ]]; then
	#         stdin_file="$PWD/$input_item"
	#     else
	#         stdin_file="$input_item"
	#     fi
	# fi
	else:
		# Stdin-only Mode
		stdin_file = os.path.abspath(input_item)

	# Copy executable/source to sandbox_dir
	# local local_exec=$(basename "$EXECUTABLE")
	# cp -r "$EXECUTABLE" "$sandbox_dir/"
	local_exec = os.path.basename(executable)
	dest_exec = os.path.join(sandbox_dir, local_exec)
	if os.path.isdir(executable):
		shutil.copytree(executable, dest_exec, dirs_exist_ok=True)
	else:
		shutil.copy2(executable, dest_exec)

	# Command array construction
	# local CMD=()
	cmd = []

	
	# TODO Problamatic If Firejail isn't installed.Python Simply doesn't use Firejail.
	# Requesting sandboxing and silently running unsandboxed is not ideal.
	
	# Firejail is Linux specific; skipped on Windows/Mac dynamically
	# if [ "$SANDBOX" = true ]; then
	#     CMD=("firejail" "--quiet" "--noprofile" "--private=.")
	# fi
	if sandbox_flag and os.name == 'posix' and shutil.which("firejail"):
		cmd += ["firejail", "--quiet", "--noprofile", "--private=."]


	# if [[ "$EXT" == ".py" ]]; then
	#     CMD+=("python3" "./$local_exec")
	# elif [[ "$EXT" == ".awk" ]]; then
	#     CMD+=("awk" "-f" "./$local_exec")
	# else
	#     CMD+=("./$local_exec")
	# fi
	if ext == ".py":
		cmd += ["python3" if os.name != 'nt' else "python", f"./{local_exec}"]
	elif ext == ".awk":
		cmd += ["awk", "-f", f"./{local_exec}"]
	else:
		if os.name == 'nt':
			cmd += [local_exec]
		else:
			cmd += [f"./{local_exec}"]

	# Load args
	# local EXTRA_ARGS=()
	# if [ -f "$args_file" ]; then
	#     EXTRA_ARGS=($(cat "$args_file"))
	# fi
	extra_args = []
	if args_file and os.path.isfile(args_file):
		try:
			with open(args_file, "r") as f:
				extra_args = f.read().split()
		except Exception:
			pass

	full_cmd = cmd + extra_args

	# Run command configuration
	stdin_stream = open(stdin_file, "r") if stdin_file else subprocess.DEVNULL
	stdout_stream = open(actual_output, "w")
	stderr_stream = open(stderr_output, "w")

	orig_cwd = os.getcwd()
	os.chdir(sandbox_dir)

	start_time = time.perf_counter()
	exit_code = 0
	timeout_occurred = False


	# TODO Problamatic The Python implementation should inspect the current limit and 
	#                   safely reduce it rather than blindly trying to increase the hard limit.

	# Unix-only memory capping configuration
	def set_limits():
		if os.name == 'posix':
			try:

				resource.setrlimit(resource.RLIMIT_AS, (memory_cap_mb * 1024 * 1024, resource.RLIMIT_INFINITY))
			except Exception:
				pass

	try:
		proc = subprocess.run(
			full_cmd,
			stdin=stdin_stream,
			stdout=stdout_stream,
			stderr=stderr_stream,
			timeout=timeout_sec,
			preexec_fn=set_limits if os.name == 'posix' else None
		)
		exit_code = proc.returncode

	# TODO produce TIMEOUT process-tree behavior can differ.
	
	except subprocess.TimeoutExpired:
		timeout_occurred = True
	except Exception as e:
		exit_code = -1
		with open(stderr_output, "a") as err_f:
			err_f.write(f"\nExecution Framework Error: {str(e)}")
	finally:
		if stdin_file:
			stdin_stream.close()
		stdout_stream.close()
		stderr_stream.close()
		os.chdir(orig_cwd)


	# TODO if /usr/bin/time isn't present, the shell leaves the execution time blank.
	# Python always generates a time.

	exec_time = time.perf_counter() - start_time


	# if [ $exit_code -eq 124 ]; then
	#     echo "[VERDICT] $test_name: TIMEOUT (${exec_time}s)"
	#     return 2
	# elif [ $exit_code -ne 0 ]; then
	#     echo "[VERDICT] $test_name: RUNTIME_ERROR (${exec_time}s)"
	#     echo "[LOG] Exit code $exit_code. Stderr:"
	#     cat "$sandbox_dir/stderr.txt" | while read -r line; do echo "[LOG] $line"; done
	#     return 3
	# fi
	if timeout_occurred:
		print(f"[VERDICT] {test_name}: TIMEOUT ({exec_time:.6f}s)")
		return 2
	elif exit_code != 0:
		print(f"[VERDICT] {test_name}: RUNTIME_ERROR ({exec_time}s)")
		print(f"[LOG] Exit code {exit_code}. Stderr:")
		if os.path.isfile(stderr_output):
			with open(stderr_output, "r", errors='ignore') as err_f:
				for line in err_f:
					print(f"[LOG] {line.rstrip()}")
		return 3

	# Diffing logic
	# if diff $DIFF_FLAGS "$actual_output" "$expected_output" > /dev/null 2>&1; then
	#     echo "[VERDICT] $test_name: PASSED (${exec_time}s)"
	#     return 0
	if diff_files(actual_output, expected_output):
		print(f"[VERDICT] {test_name}: PASSED ({exec_time}s)")
		return 0

	# else
	#     echo "[VERDICT] $test_name: WRONG_ANSWER (${exec_time}s)"
	#     echo "[LOG] Diff snippet (Expected vs Actual):"
	#     diff -u --color=always "$expected_output" "$actual_output" | head -n 15 | while read -r line; do echo "[LOG] $line"; done
	#     return 1
	# fi
	else:
		print(f"[VERDICT] {test_name}: WRONG_ANSWER ({exec_time}s)")
		print("[LOG] Diff snippet (Expected vs Actual):")
		print_diff_snippet(actual_output, expected_output)
		return 1

def main():
	args = parse_arguments()
	evaluator, timeout_sec, memory_cap_mb, makefile_mode, exec_name = load_config(
		args.config, 
		args.question
		)

	# Detect extension
	# FILENAME=$(basename "$SUBMISSION")
	# EXT="${FILENAME##*.}"
	# if [[ "$FILENAME" == "$EXT" ]]; then
	# 	EXT=""
	# else
	# 	EXT=".$EXT"
	# fi

	filename = os.path.basename(args.submission)
	name_part, ext = os.path.splitext(filename)


	# Compilation step (if not using custom evaluator that handles compilation)
	# Actually, we should compile if it's .c or .cpp
	# EXECUTABLE="$SUBMISSION"
	# BUILD_DIR=$(mktemp -d -t ig_build_XXXXXX)
	# trap 'rm -rf "$BUILD_DIR"' EXIT

	executable = args.submission
	build_dir = tempfile.mkdtemp(prefix="ig_build_")

	try:
		# if [ "$MAKEFILE_MODE" == "true" ]; then
		if makefile_mode:
			# if [ ! -d "$SUBMISSION" ]; then
			# 	echo "[LOG] Error: Expected a directory for Makefile project, got file: $SUBMISSION"
			# 	echo "[VERDICT] ALL: COMPILATION_ERROR"
			# 	exit 1
			# fi
			if not os.path.isdir(args.submission):
				print(f"[LOG] Error: Expected a directory for Makefile project, got file: {args.submission}")
				print("[VERDICT] ALL: COMPILATION_ERROR")
				sys.exit(1)


			# TODO Problamatic Python copytree() copy hidden files.
			
			# echo "[LOG] Compiling via Makefile in temporary sandbox..."
			# cp -r "$SUBMISSION"/* "$BUILD_DIR/"
			# if [ -d "${TESTCASES_DIR}/static" ]; then
			# 	cp -rf "${TESTCASES_DIR}/static/"* "$BUILD_DIR/" 2>/dev/null
			# fi
			print("[LOG] Compiling via Makefile in temporary sandbox...")
			shutil.copytree(args.submission, build_dir, dirs_exist_ok=True)
			static_dir = os.path.join(args.testcases_dir, "static")
			if os.path.isdir(static_dir):
				shutil.copytree(static_dir, build_dir, dirs_exist_ok=True)

			# if [ -d "${TESTCASES_DIR}/${QUESTION}/static" ]; then
			# 	cp -rf "${TESTCASES_DIR}/${QUESTION}/static/"* "$BUILD_DIR/" 2>/dev/null
			# fi
			q_static_dir = os.path.join(args.testcases_dir, args.question, "static")
			if os.path.isdir(q_static_dir):
				shutil.copytree(q_static_dir, build_dir, dirs_exist_ok=True)

			orig_dir = os.getcwd()
			os.chdir(build_dir)
			
			compile_log = "compile_log.txt"
			make_cmd = ["make"] if os.name != 'nt' else ["mingw32-make", "make"]
			
			success = False
			for cmd in make_cmd:
				if shutil.which(cmd):
					with open(compile_log, "w") as log_f:
						res = subprocess.run(
							[cmd],
						   stdout=log_f,
						   stderr=subprocess.STDOUT
						   )
						success = (res.returncode == 0)
					break
			else:
				with open(compile_log, "w") as log_f:
					log_f.write(
						"No 'make' engine tool found on this OS environment."
						)
					success = False

			# if ! make > "compile_log.txt" 2>&1; then
			# 	echo "[COMPILE_LOG] Compilation failed:"
			# 	cat "compile_log.txt" | while read -r line; do echo "[COMPILE_LOG] $line"; done
			# 	echo "[VERDICT] ALL: COMPILATION_ERROR"
			# 	exit 1
			# fi
			
			if not success:
				print("[COMPILE_LOG] Compilation failed:")
				if os.path.isfile(compile_log):
					with open(compile_log, "r") as log_f:
						for line in log_f:
							print(f"[COMPILE_LOG] {line.rstrip()}")
				print("[VERDICT] ALL: COMPILATION_ERROR")
				sys.exit(1)

			# EXECUTABLE="${BUILD_DIR}/${EXEC_NAME}"
			# cd - >/dev/null
			
			executable = os.path.join(build_dir, exec_name)
			os.chdir(orig_dir)


		# elif [[ "$EXT" == ".c" ]]; then
		elif ext == ".c":
			# EXECUTABLE="${BUILD_DIR}/exec"
			# echo "[LOG] Compiling C source..."
			executable = os.path.join(
				build_dir,
				"exec" + (".exe" if os.name == 'nt' else "")
			)
			print("[LOG] Compiling C source...")

			compile_err = os.path.join(build_dir, "compile_err.txt")

			with open(compile_err, "w") as err_f:
				res = subprocess.run(
					["gcc"] + CFLAGS + [args.submission] + LDFLAGS + ["-o", executable], 
					stderr=err_f
				)

			# if ! gcc $CFLAGS "$SUBMISSION" $LDFLAGS -o "$EXECUTABLE" 2> "${BUILD_DIR}/compile_err.txt"; then
			# 	echo "[COMPILE_LOG] Compilation failed:"
			# 	cat "${BUILD_DIR}/compile_err.txt" | while read -r line; do echo "[COMPILE_LOG] $line"; done
			# 	echo "[VERDICT] ALL: COMPILATION_ERROR"
			# 	exit 1
			# fi
			if res.returncode != 0:
				print("[COMPILE_LOG] Compilation failed:")
				with open(compile_err, "r") as err_f:
					for line in err_f:
						print(f"[COMPILE_LOG] {line.rstrip()}")
				print("[VERDICT] ALL: COMPILATION_ERROR")
				sys.exit(1)

		# elif [[ "$EXT" == ".cpp" ]]; then
		elif ext == ".cpp":

			# EXECUTABLE="${BUILD_DIR}/exec"
			# echo "[LOG] Compiling C++ source..."
			executable = os.path.join(
				build_dir, 
				"exec" + (".exe" if os.name == 'nt' else "")
			)

			print("[LOG] Compiling C++ source...")

			compile_err = os.path.join(build_dir, "compile_err.txt")

			with open(compile_err, "w") as err_f:
				res = subprocess.run(
					["g++"] + CXXFLAGS + [args.submission] + LDFLAGS + ["-o", executable], 
					stderr=err_f
				)

			# if ! g++ $CXXFLAGS "$SUBMISSION" $LDFLAGS -o "$EXECUTABLE" 2> "${BUILD_DIR}/compile_err.txt"; then
			# 	echo "[COMPILE_LOG] Compilation failed:"
			# 	cat "${BUILD_DIR}/compile_err.txt" | while read -r line; do echo "[COMPILE_LOG] $line"; done
			# 	echo "[VERDICT] ALL: COMPILATION_ERROR"
			# 	exit 1
			# fi
			if res.returncode != 0:
				print("[COMPILE_LOG] Compilation failed:")
				with open(compile_err, "r") as err_f:
					for line in err_f:
						print(f"[COMPILE_LOG] {line.rstrip()}")
				print("[VERDICT] ALL: COMPILATION_ERROR")
				sys.exit(1)



		# # Make EXECUTABLE absolute if it's not already
		# if [[ ! "$EXECUTABLE" == /* ]]; then
		# 	EXECUTABLE="$PWD/$EXECUTABLE"
		# fi
		if not os.path.isabs(executable):
			executable = os.path.abspath(executable)


		# Run tests
		# TOTAL=0
		# PASSED=0

		# # Ensure testcases dir exists
		# Q_INPUT_DIR="$TESTCASES_DIR/$QUESTION/input"
		# Q_OUTPUT_DIR="$TESTCASES_DIR/$QUESTION/output"

		# if [ ! -d "$Q_INPUT_DIR" ]; then
		# 	echo "[LOG] No input directory found at $Q_INPUT_DIR"
		# 	exit 1
		# fi

		total_tests = 0
		passed_tests = 0
		q_input_dir = os.path.join(args.testcases_dir, args.question, "input")
		q_output_dir = os.path.join(args.testcases_dir, args.question, "output")
		
		if not os.path.isdir(q_input_dir):
			print(f"[LOG] No input directory found at {q_input_dir}")
			sys.exit(1)



		# Python will attempt to grade Hidden file (eg; .input01) while shell won't.

		input_items = sorted(
			os.listdir(q_input_dir)
		)

		# for input_item in "$Q_INPUT_DIR"/*; do
		# 	[ -e "$input_item" ] || continue
		for item in input_items:

			# TODO This means Python performs only one prefix removal.

			# test_case_name=$(basename "$input_item" | sed -e 's/^input//' -e 's/^args//')
			input_item_path = os.path.join(q_input_dir, item)
			test_case_name = item

			if test_case_name.startswith("input"):
				test_case_name = test_case_name[5:]

			elif test_case_name.startswith("args"):
				test_case_name = test_case_name[4:]

			# if [[ "$test_case_name" == *.txt ]]; then
			# 	test_case_name="${test_case_name%.txt}"
			# fi
			if test_case_name.endswith(".txt"):
				test_case_name = test_case_name[:-4]

			# # Targeted testcase filter
			# if [ -n "$TARGET_TESTCASE" ]; then
			# 	# Strip leading zeros for a fair numerical comparison (so 4 == 04)
			# 	stripped_target=$(echo "$TARGET_TESTCASE" | sed 's/^0*//')
			# 	stripped_current=$(echo "$test_case_name" | sed 's/^0*//')
			# 	if [ "$stripped_current" != "$stripped_target" ]; then
			# 		continue
			# 	fi
			# fi
			if args.testcase:
				stripped_target = strip_leading_zeros(args.testcase)
				stripped_current = strip_leading_zeros(test_case_name)

				if stripped_current != stripped_target:
					continue


			# TOTAL=$((TOTAL + 1))
			total_tests += 1

			# expected_output="$Q_OUTPUT_DIR/output${test_case_name}"
			expected_output = os.path.join(
				q_output_dir, 
				f"output{test_case_name}"
			)
			
			# # Might be a .txt or a directory
			# if [ ! -e "$expected_output" ] && [ -e "${expected_output}.txt" ]; then
			# 	expected_output="${expected_output}.txt"
			# fi
			if (
				not os.path.exists(expected_output) 
	   			and os.path.exists(expected_output + ".txt")
			):
				expected_output += ".txt"


			# sandbox_dir=$(mktemp -d -t sandbox_XXXXXX)
			sandbox_dir = tempfile.mkdtemp(prefix="sandbox_")

			try:
				# # Evaluate
				# if [ -n "$EVALUATOR" ] && [ "$EVALUATOR" != "null" ]; then
				if evaluator and evaluator != "null":


					# Custom Evaluation
					# # Resolve to absolute paths if evaluator assumes it
					# EVAL_SCRIPT="$(cd $(dirname "$CONFIG_FILE") && pwd)/$EVALUATOR"
					# if [ ! -x "$EVAL_SCRIPT" ]; then
					# 	chmod +x "$EVAL_SCRIPT"
					# fi
					eval_script = os.path.abspath(
						os.path.join(
							os.path.dirname(args.config), 
							evaluator
							)
						)

					# TODO Python doesn't chmod. If evaluator exists but isn't executable grader can crash
					
					# Pass EXECUTABLE, input_item, expected_output, sandbox_dir, timeout, sandbox_flag
					# "$EVAL_SCRIPT" "$EXECUTABLE" "$input_item" "$expected_output" "$sandbox_dir" "$TIMEOUT_SEC" "$SANDBOX"
					# exit_code=$?
					run_args = [
						executable, 
						input_item_path, 
						expected_output, 
						sandbox_dir, 
						str(timeout_sec), 
						str(args.sandbox).lower()
				 ]
					
					if os.name == 'nt' and eval_script.endswith('.sh'):
						eval_cmd = ["bash", eval_script] + run_args
					else:
						eval_cmd = [eval_script] + run_args

					res = subprocess.run(
						eval_cmd
					)

					# exit_code=$?
					exit_code = res.returncode


					# if [ $exit_code -eq 0 ]; then
					# 	echo "[VERDICT] $test_case_name: PASSED"
					# 	PASSED=$((PASSED + 1))
					if exit_code == 0:
						print(f"[VERDICT] {test_case_name}: PASSED")

						passed_tests += 1



					# TODO Shell → TIMEOUT Python → WRONG_ANSWER
					# elif [ $exit_code -eq 124 ] || [ $exit_code -eq 2 ]; then
					# 	echo "[VERDICT] $test_case_name: TIMEOUT"
					elif exit_code == 2:
						print(f"[VERDICT] {test_case_name}: TIMEOUT")
						
					# elif [ $exit_code -eq 3 ]; then
					# 	echo "[VERDICT] $test_case_name: RUNTIME_ERROR"
					elif exit_code == 3:
						print(f"[VERDICT] {test_case_name}: RUNTIME_ERROR")

					# else
					# 	echo "[VERDICT] $test_case_name: WRONG_ANSWER"
					# fi
					else:
						print(f"[VERDICT] {test_case_name}: WRONG_ANSWER")


				else:
					# # Standard Evaluation
					# run_standard "$input_item" "$expected_output" "$sandbox_dir" "$test_case_name"
					rc = run_standard(
						executable, 
						input_item_path, 
						expected_output, 
						sandbox_dir,
						test_case_name, 
						ext, 
						timeout_sec, 
						memory_cap_mb,
						args.sandbox, 
						args.testcases_dir, 
						args.question
					)

					# exit_code=$?
					# if [ $exit_code -eq 0 ]; then
					# 	PASSED=$((PASSED + 1))
					# fi
					if rc == 0:
						passed_tests += 1


				# if [ -n "$SAVE_OUTPUT_DIR" ]; then
				# 	mkdir -p "$SAVE_OUTPUT_DIR"
				# 	cp "$sandbox_dir/stdout.txt" "$SAVE_OUTPUT_DIR/${QUESTION}_output${test_case_name}.txt" 2>/dev/null || true
				# fi
				if args.save_output_dir:
					os.makedirs(args.save_output_dir, exist_ok=True)
					src_stdout = os.path.join(sandbox_dir, "stdout.txt")

					if os.path.isfile(src_stdout):
						shutil.copy2(
							src_stdout, 
							os.path.join(
								args.save_output_dir, 
								f"{args.question}_output{test_case_name}.txt"
								)
							)
						
			finally:
				# rm -rf "$sandbox_dir"
				shutil.rmtree(sandbox_dir, ignore_errors=True)

		# echo "[SCORE] $PASSED/$TOTAL"
		print(f"[SCORE] {passed_tests}/{total_tests}")


	finally:
		shutil.rmtree(build_dir, ignore_errors=True)

if __name__ == "__main__":
	main()
