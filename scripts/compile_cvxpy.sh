cd cvxpy || exit
sh rebuild_cvxcore.sh
sed -i 's/from . import _cvxcore/import _cvxcore/' cvxpy/cvxcore/python/cvxcore.py