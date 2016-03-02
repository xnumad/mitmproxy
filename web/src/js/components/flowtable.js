import React from "react";
import ReactDOM from 'react-dom';
import {AutoScrollMixin} from "./common.js";
import {reverseString} from "../utils.js";
import _ from "lodash";

import VirtualScrollMixin from "./virtualscroll.js"
import flowtable_columns from "./flowtable-columns.js";

var FlowRow = React.createClass({
    render: function () {
        var flow = this.props.flow;
        var columns = this.props.columns.map(function (Column) {
            return <Column key={Column.displayName} flow={flow}/>;
        }.bind(this));
        var className = "";
        if (this.props.selected) {
            className += " selected";
        }
        if (this.props.highlighted) {
            className += " highlighted";
        }
        if (flow.intercepted) {
            className += " intercepted";
        }
        if (flow.request) {
            className += " has-request";
        }
        if (flow.response) {
            className += " has-response";
        }

        return (
            <tr className={className} onClick={this.props.selectFlow.bind(null, flow)}>
                {columns}
            </tr>);
    },
    shouldComponentUpdate: function (nextProps) {
        return true;
        // Further optimization could be done here
        // by calling forceUpdate on flow updates, selection changes and column changes.
        //return (
        //(this.props.columns.length !== nextProps.columns.length) ||
        //(this.props.selected !== nextProps.selected)
        //);
    }
});

var FlowTableHead = React.createClass({
    getInitialState: function(){
        return {
            sortColumn: undefined,
            sortDesc: false
        };
    },
    onClick: function(Column){
        var sortDesc = this.state.sortDesc;
        var hasSort = Column.sortKeyFun;
        if(Column === this.state.sortColumn){
            sortDesc = !sortDesc;
            this.setState({
                sortDesc: sortDesc
            });
        } else {
            this.setState({
                sortColumn: hasSort && Column,
                sortDesc: false
            })
        }
        var sortKeyFun;
        if(!sortDesc){
            sortKeyFun = Column.sortKeyFun;
        } else {
            sortKeyFun = hasSort && function(){
                var k = Column.sortKeyFun.apply(this, arguments);
                if(_.isString(k)){
                    return reverseString(""+k);
                } else {
                    return -k;
                }
            }
        }
        this.props.setSortKeyFun(sortKeyFun);
    },
    render: function () {
        var columns = this.props.columns.map(function (Column) {
            var onClick = this.onClick.bind(this, Column);
            var className;
            if(this.state.sortColumn === Column) {
                if(this.state.sortDesc){
                    className = "sort-desc";
                } else {
                    className = "sort-asc";
                }
            }
            return <Column.Title
                        key={Column.displayName}
                        onClick={onClick}
                        className={className} />;
        }.bind(this));
        return <thead>
            <tr>{columns}</tr>
        </thead>;
    }
});


class FlowList extends React.Component {
    onScroll(){
        var head = ReactDOM.findDOMNode(this.refs.head);
        head.style.transform = "translate(0," + ReactDOM.findDOMNode(this).scrollTop + "px)";
        this.props.onScroll();
    }
    render() {
        const props = this.props;
        const rows = props.elements.map((flow) => {
            var selected = (flow === props.selected);
            var highlighted = props.highlight[flow.id];

            return <FlowRow key={flow.id}
                            flow={flow}
                            columns={props.columns}
                            selected={selected}
                            highlighted={highlighted}
                            selectFlow={props.selectFlow}
            />;
        });
        return <div className="flow-table" onScroll={() => this.onScroll()}>
            <table>
                <FlowTableHead
                    ref="head"
                    columns={props.columns}
                    setSortKeyFun={props.setSortKeyFun}/>
                <tbody>
                { props.placeholderTop }
                {rows}
                { props.placeholderBottom }
                </tbody>
            </table>
        </div>;
    }
}
FlowList = AutoScrollMixin(FlowList);
FlowList = VirtualScrollMixin(FlowList, {
    rowHeight: 32,
    placeholder: "tr",
    headHeight: 23
});


var FlowTable = React.createClass({
    contextTypes: {
        view: React.PropTypes.object.isRequired
    },
    getInitialState: function () {
        return {
            columns: flowtable_columns
        };
    },
    componentWillMount: function () {
        this.context.view.addListener("add", this.onChange);
        this.context.view.addListener("update", this.onChange);
        this.context.view.addListener("remove", this.onChange);
        this.context.view.addListener("recalculate", this.onChange);
    },
    componentWillUnmount: function(){
        this.context.view.removeListener("add", this.onChange);
        this.context.view.removeListener("update", this.onChange);
        this.context.view.removeListener("remove", this.onChange);
        this.context.view.removeListener("recalculate", this.onChange);
    },
    onScrollFlowTable: function () {
        this.adjustHead();
    },
    onChange: function () {
        this.forceUpdate();
    },
    scrollIntoView: function (flow) {
        this.refs.flowList.scrollRowIntoView(
            this.context.view.index(flow)
        );
    },
    render: function () {
        const flows = this.context.view.list;
        return <FlowList
            ref="flowList"
            elements={flows}
            selected={this.props.selected}
            highlight={this.context.view._highlight || {}}
            columns={this.state.columns}
            selectFlow={this.props.selectFlow}
            setSortKeyFun={this.props.setSortKeyFun}
        />;
    }
});

export default FlowTable;
