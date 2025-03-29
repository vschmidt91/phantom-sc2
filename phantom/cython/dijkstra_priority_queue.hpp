#include <functional>
#include <queue>
#include <utility>

using coords = std::pair<Py_ssize_t,Py_ssize_t>;
using item = std::pair<float,coords>;
using cpp_pq = std::priority_queue<item,std::vector<item>,std::function<bool(item,item)>>;