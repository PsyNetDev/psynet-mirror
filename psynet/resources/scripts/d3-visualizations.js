"use strict";

function toTwoDecimals(float_or_string) {
    if (typeof float_or_string !== 'string') {
        return float_or_string.toFixed(2);
    } else {
        return float_or_string;
    }
}

function scatter(containerId, data, margin, xLabel, yLabel, tooltip = null) {
    let hold = false;
    var container = document.getElementById(containerId);
    var width = container.clientWidth;
    width = width - margin.left - margin.right;
    var height = width - margin.top - margin.bottom;
    var svg = d3.select(`#${containerId}`)
        .append("svg")
        .attr("width", width + margin.left + margin.right)
        .attr("height", height + margin.top + margin.bottom)
        .append("g")
        .attr("transform",
            `translate(${margin.left},${margin.top})`);

    let xMin = d3.min(data, function (d) {
        return d.x;
    });
    let xMax = d3.max(data, function (d) {
        return d.x;
    });

    let yMin = d3.min(data, function (d) {
        return d.y;
    });
    let yMax = d3.max(data, function (d) {
        return d.y;
    });

    xMax = 1.1 * xMax;
    yMax = 1.1 * yMax;

    var x = d3.scaleLinear()
        .domain([0, xMax])
        .range([0, width]);


    var y = d3.scaleLinear()
        .range([height, 0])
        .domain([0, yMax]);

    // add axis
    svg.append("g")
        .attr("transform", `translate(0,${height})`)
        .call(d3.axisBottom(x));

    svg.append("g")
        .call(d3.axisLeft(y));

    // add x = y line
    let totalMin = Math.min(xMin, yMin);
    let totalMax = Math.max(xMax, yMax);
    svg.append("line")
        .attr("x1", x(0))
        .attr("y1", y(0))
        .attr("x2", x(totalMax))
        .attr("y2", y(totalMax))
        .attr("stroke", "black")
        .attr("stroke-width", 1)
        .attr("stroke-dasharray", "5,5");


    // axis labels
    svg.append("text")
        .attr("text-anchor", "end")
        .attr("x", width / 2 + margin.left)
        .attr("y", height + margin.bottom)
        .style("font-size", "12px")
        .text(xLabel);

    svg.append("text")
        .attr("text-anchor", "end")
        .attr("transform", "rotate(-90)")
        .attr("y", -margin.left + 10)
        .attr("x", -height / 2 + margin.top)
        .style("font-size", "12px")
        .text(yLabel);


    // Make a scatter plot
    svg.append('g')
        .selectAll("dot")
        .data(data)
        .enter()
        .append("circle")
        .attr("cx", function (d) {
            return x(d.x);
        })
        .attr("cy", function (d) {
            return y(d.y);
        })
        .attr("r", 3)
        .style("fill", function (d) {
            return "black";
        })
        .style("opacity", 0.5)
        .on('mouseover', function (d) {
            if (tooltip !== null) {
                tooltip.show(d, this);
            }
        })
        .on('mouseout', function (d) {
            if (tooltip !== null) {
                tooltip.hide(d, this);
            }
        });

    if (tooltip !== null) {
        svg.call(tooltip);
    }
}

function hideTooltips() {
    d3.selectAll('.d3-tip').style('opacity', 0);
}

function histogram(containerId, data, margin, nBins, type2color, tooltip = null, height = null, xDict= null, plotGrouped=true) {
    // set the dimensions and margins of the graph
    var container = document.getElementById(containerId);
    var width = container.clientWidth;
    width = width - margin.left - margin.right;
    if (height === null) {
        height = width - margin.top - margin.bottom;
    }

    // append the svg object to the body of the page
    var svg = d3.select("#" + containerId)
        .append("svg")
        .attr("width", width + margin.left + margin.right)
        .attr("height", height + margin.top + margin.bottom)
        .append("g")
        .attr("transform",
            `translate(${margin.left},${margin.top})`);


    // get the data
    data = data.map(function (d) {
        d['value'] = parseFloat(d['value']);
        d['group'] = d['type']
        if (!plotGrouped){
            d['type'] = 'none';
        }
        return d;
    });
    const xMin = d3.min(data, function (d) {
        return +d.value;
    });
    const xMax = d3.max(data, function (d) {
        return +d.value;
    });
    // X axis: scale and draw:
    var x = d3.scaleLinear()
        .domain([xMin, xMax])     // can use this instead of 1000 to have the max of data: d3.max(data, function(d) { return +d.price })
        .range([0, width]);
    const uniqueTypes = [...new Set(data.map(d => d.type))]
    svg.append("g")
        .attr("transform", `translate(0,${height})`)
        .call(d3.axisBottom(x));


    // format x axis text
    svg.selectAll("#" + containerId + " .tick text")
        // change text to date format
        .text(function (d) {
            if (xDict !== null) {
                return xDict[d];
            }
            return d;
        });
    // set the parameters for the histogram
    var histogram = d3.histogram()
        .value(function (d) {
            return +d.value;
        })   // I need to give the vector of value
        .domain(x.domain())  // then the domain of the graphic
        .thresholds(x.ticks(nBins)); // then the numbers of bins
    // And apply twice this function to data to get the bins.
    var allBins = [];
    for (var i = 0; i < uniqueTypes.length; i++) {
        var bins = histogram(data.filter(function (d) {
            return d.type === uniqueTypes[i]
        }));
        allBins.push(bins)
    }
    let maxY = d3.max(allBins, function (bins) {
        return d3.max(bins, function (bin) {
            return bin.length
        })
    })
    // Y axis: scale and draw:
    var y = d3.scaleLinear()
        .range([height, 0]);
    y.domain([0, maxY]);   // d3.hist has to be called before the Y axis obviously
    svg.append("g")
        .call(d3.axisLeft(y));
    const nGroups = uniqueTypes.length
    // grouped histogram with different colors
    allBins.forEach(function (bins, i) {
        const type = uniqueTypes[i];
        const color = type2color[type];
        svg.selectAll(`rect${i}`)
            .data(bins)
            .enter()
            .append("rect")
            .attr("x", function (d) {
                return i * ((x(d.x1) - x(d.x0)) / nGroups);
            })
            .attr("transform", function (d) {
                return `translate(${x(d.x0)},${y(d.length)})`;
            })
            .attr("width", function (d) {
                return (x(d.x1) - x(d.x0)) / nGroups;
            })
            .attr("height", function (d) {
                return height - y(d.length);
            })
            .style("fill", function () {
                return color;
            })
            .style("opacity", 0.6)
            .on('mouseover', function (d) {
                d3.select(this).style('opacity', 1);
            })
            .on('mouseout', function (d) {
                d3.select(this).style('opacity', 0.6);
            })
            .on('click', function (d) {
                if (tooltip !== null) {
                    tooltip.show(d, this);
                }
            });
    });
    if (tooltip !== null) {
        svg.call(tooltip);
    }
    if (uniqueTypes.length > 1) {
        uniqueTypes.forEach(function (type, i) {
            svg.append("circle")
                .attr("cx", width - 30)
                .attr("cy", i * 20)
                .attr("r", 6)
                .style("fill", type2color[type]);
            svg.append("text")
                .attr("x", width - 20)
                .attr("y", i * 20)
                .text(type)
                .style("font-size", "10px")
                .attr("alignment-baseline", "middle");
        })
    }
}

function linePlot(containerId, data, margin, xLabel, yLabel, tooltip = null, height = null, yLimits = null, type2color = null, xDict=null) {
    const uniqueTypes = [...new Set(data.map(d => d.type))]
    if (type2color === null) {
        type2color = {};
        uniqueTypes.forEach(function (type, i) {
            type2color[type] = d3.schemeCategory10[i];
        });
    }
    var container = document.getElementById(containerId);
    var width = container.clientWidth;
    width = width - margin.left - margin.right;
    if (height === null) {
        height = width - margin.top - margin.bottom;
    }

    var svg = d3.select(`#${containerId}`)
        .append("svg")
        .attr("width", width + margin.left + margin.right)
        .attr("height", height + margin.top + margin.bottom)
        .append("g")
        .attr("transform",
            `translate(${margin.left},${margin.top})`);
    let xMin = d3.min(data, function (d) {
        return d.x;
    });
    let xMax = d3.max(data, function (d) {
        return d.x;
    });
    let yMin, yMax;
    if (yLimits === null) {
        yMin = d3.min(data, function (d) {
            return d.y;
        });
        yMax = d3.max(data, function (d) {
            return d.y;
        });
    } else {
        yMin = yLimits[0];
        yMax = yLimits[1];
    }
    var x = d3.scaleLinear()
        .domain([xMax, xMin])
        .range([0, width]);
    var y = d3.scaleLinear()
        .range([height, 0])
        .domain([yMin, yMax]);
    svg.append("g")
        .attr("transform", `translate(0,${height})`)
        .call(d3.axisBottom(x));

    // format x axis text
    svg.selectAll(".tick text")
        // change text to date format
        .text(function (d) {
            if (xDict !== null) {
                return xDict[d];
            }
            return d;
        });


    svg.append("g")
        .call(d3.axisLeft(y));
    svg.append("text")
        .attr("text-anchor", "end")
        .attr("x", width / 2 + margin.left)
        .attr("y", height + margin.bottom)
        .style("font-size", "12px")
        .text(xLabel);
    svg.append("text")
        .attr("text-anchor", "end")
        .attr("transform", "rotate(-90)")
        .attr("y", -margin.left + 10)
        .attr("x", -height / 2 + margin.top)
        .style("font-size", "12px")
        .text(yLabel);

    // add line
    var line = d3.line()
        .x(function (d) {
            return x(d.x);
        })
        .y(function (d) {
            return y(d.y);
        });
    uniqueTypes.forEach(function (type, i) {
        svg.append("path")
            .datum(data.filter(function (d) {
                return d.type === type;
            }))
            .attr("fill", "none")
            .attr("stroke", type2color[type])
            .attr("stroke-width", 1.5)
            .attr("d", line);
    });

    svg.append('g')
        .attr("id", `selection`)

    svg.append('g')
        .selectAll("dot")
        .data(data)
        .enter()
        .append("circle")
        .attr("cx", function (d) {
            return x(d.x);
        })
        .attr("cy", function (d) {
            return y(d.y);
        })
        .attr("r", 3)
        .style("fill", function (d){
            return type2color[d.type];
        })
        .on('mouseover', function (d) {
            // mark current x coordinate with vertical line
            d3.select(`#selection`).append('line')
                .attr("x1", x(d.x))
                .attr("y1", 0)
                .attr("x2", x(d.x))
                .attr("y2", height)
                .attr("stroke", "gray")
                .attr("stroke-width", 1)
                .attr("stroke-dasharray", "5,5");
            if (tooltip !== null) {
                tooltip.show(d, this);
            }
        })
        .on('mouseout', function (d) {
            d3.select(`#selection`).selectAll('line').remove();
            if (tooltip !== null) {
                tooltip.hide(d, this);
            }
        });

    if (tooltip !== null) {
        svg.call(tooltip);
    }

    if (uniqueTypes.length > 1) {
        uniqueTypes.forEach(function (type, i) {
            let leftPadding = 200;
            svg.append("circle")
                .attr("cx", width - (leftPadding + 10))
                .attr("cy", i * 20)
                .attr("r", 6)
                .style("fill", type2color[type]);
            svg.append("text")
                .attr("x", width - leftPadding)
                .attr("y", i * 20)
                .text(type)
                .style("font-size", "10px")
                .attr("alignment-baseline", "middle");
        })
    }
}
