import React from "react"
import ReactDOM from "react-dom"
import {Router} from "../common.js"
import Nav from "./nav.js"
import {Request, Response, Error} from "./messages.js"
import Details from "./details.js"
import Prompt from "../prompt.js"


var allTabs = {
    request: Request,
    response: Response,
    error: Error,
    details: Details
};

var FlowView = React.createClass({
    mixins: [Router],
    getInitialState: function () {
        return {
            prompt: false
        };
    },
    getTabs: function (flow) {
        var tabs = [];
        ["request", "response", "error"].forEach(function (e) {
            if (flow[e]) {
                tabs.push(e);
            }
        });
        tabs.push("details");
        return tabs;
    },
    nextTab: function (i) {
        var tabs = this.getTabs(this.props.flow);
        var currentIndex = tabs.indexOf(this.props.tab);
        // JS modulo operator doesn't correct negative numbers, make sure that we are positive.
        var nextIndex = (currentIndex + i + tabs.length) % tabs.length;
        this.selectTab(tabs[nextIndex]);
    },
    selectTab: function (panel) {
        this.updateLocation(`/flows/${this.props.flow.id}/${panel}`);
    },
    promptEdit: function () {
        var options;
        switch (this.props.tab) {
            case "request":
                options = [
                    "method",
                    "url",
                    {text: "http version", key: "v"},
                    "header"
                    /*, "content"*/];
                break;
            case "response":
                options = [
                    {text: "http version", key: "v"},
                    "code",
                    "message",
                    "header"
                    /*, "content"*/];
                break;
            case "details":
                return;
            default:
                throw "Unknown tab for edit: " + this.props.tab;
        }

        this.setState({
            prompt: {
                done: function (k) {
                    this.setState({prompt: false});
                    if (k) {
                        this.refs.tab.edit(k);
                    }
                }.bind(this),
                options: options
            }
        });
    },
    onScroll: function(){
        var head = ReactDOM.findDOMNode(this.refs.head);
        head.style.transform = "translate(0," + ReactDOM.findDOMNode(this).scrollTop + "px)";
    },
    render: function () {
        var flow = this.props.flow;
        var tabs = this.getTabs(flow);
        var active = this.props.tab;

        if (tabs.indexOf(active) < 0) {
            if (active === "response" && flow.error) {
                active = "error";
            } else if (active === "error" && flow.response) {
                active = "response";
            } else {
                active = tabs[0];
            }
            this.selectTab(active);
        }

        var prompt = null;
        if (this.state.prompt) {
            prompt = <Prompt {...this.state.prompt}/>;
        }

        var Tab = allTabs[active];
        return (
            <div className="flow-detail" onScroll={this.onScroll}>
                <Nav ref="head"
                     flow={flow}
                     tabs={tabs}
                     active={active}
                     selectTab={this.selectTab}/>
                <Tab ref="tab" flow={flow}/>
                {prompt}
            </div>
        );
    }
});

export default FlowView;